# Propuesta a P2 · Cambios al contrato SQL (de P1)

- **Estado:** **aplicada por P2** (verificada en vivo por P1 el 2026-11-20: función, secuencia, índice, permisos por columna,
  esquema `orquestador` y fragmentos sin vector = 0). Propuesta original del 2026-11-19.
- **Por qué:** P1 no toca `db/` ni cambia el contrato por su cuenta. Aquí está todo lo que el backend necesita de la BD,
  con el SQL listo para que P2 lo revise y lo agregue a sus migraciones. Ver la verificación al final.
- **Comprobado contra la BD viva** (rol `app_backend` → `app_rw`): `app_rw` solo puede **leer** `conocimiento.articulos`
  y `kb_fragmentos`; puede leer, insertar y actualizar `conocimiento.propuestas_kb`.

| # | Cambio | Prioridad | Qué pasa mientras no esté |
|---|---|---|---|
| 1 | Función `conocimiento.publicar_propuesta` | **Alta (demo del Módulo A)** | «Publicar» deja la propuesta `aprobada`; no entra a la KB |
| 2 | `setval` de `operacion.incidentes_seq` en la semilla | Media | El backend reintenta con otro id (funciona, pero ensucia los logs) |
| 3 | Índice único de idempotencia en `propuestas_kb` | Media | La idempotencia del lote solo la garantiza el backend |
| 4 | Esquema `orquestador` para el *checkpointer* | Baja | Rehidratación desde la ITSM (ADR 0018): se pierde como mucho el turno en curso |
| 5 | Re-embeber fragmentos con `embedding` nulo | Baja | Un artículo publicado sin vector se encuentra solo por búsqueda léxica |
| 6 | Túnel con nombre (dirección fija) | **Alta (demo)** | El túnel temporal cae y cambia de dirección (pasó 4 veces el 19-nov) |

---

## 1. Publicar una propuesta aprobada en la KB

La escritura sigue fuera de `app_rw`: la función es `SECURITY DEFINER` y es lo único que el backend puede
ejecutar. El backend le envía los fragmentos ya partidos por sección y embebidos con el mismo modelo de la KB
(`qwen3-embedding:0.6b`, 1024 dims). Antes, el backend valida el borrador: nada de «por redactar/confirmar»,
síntoma, causa y pasos presentes, y título y secciones limpios para la guardia (inyección, acciones prohibidas,
identidad).

**La función no confía en el llamador** (revisión de seguridad P1, 2026-11-19):
- Cada fragmento debe ser **texto literal del `borrador_md`** guardado en la propuesta. El resumen debe empezar por
  el título. Así, quien tenga `app_rw` no puede colar pasos distintos de los que vio el revisor.
- El `contenido_md` del artículo se **reconstruye** con las secciones validadas. El pie y «Cambios propuestos» nunca
  entran a la KB.
- Una corrección exige que el artículo exista y no esté `retirado`.
- `search_path` fijo con `pg_temp` al final, y los tipos de pgvector calificados (`public.vector`; si pgvector vive
  en otro esquema, ajustar).

```sql
create or replace function conocimiento.publicar_propuesta(
    p_propuesta_id bigint,
    p_revisor_id   text,
    p_fragmentos   jsonb,          -- [{seccion, orden, texto, embedding: [float] | null}]
    p_modelo       text default null
) returns text
language plpgsql
security definer
set search_path = pg_catalog, conocimiento, pg_temp
as $$
declare
    v_p        conocimiento.propuestas_kb%rowtype;
    v_id       text;
    v_f        jsonb;
    v_texto    text;
    v_seccion  text;
    v_vec      public.vector;
    v_md       text;
    v_contenido text;
begin
    -- 1. Revisor real y con el rol correcto.
    if not exists (select 1 from org.usuarios
                    where id = p_revisor_id and rol = 'revisor_kb' and coalesce(activo, true)) then
        raise exception 'revisor % no autorizado', p_revisor_id;
    end if;

    -- 2. Propuesta existente y aún publicable (bloqueo: dos revisores no publican a la vez).
    select * into v_p from conocimiento.propuestas_kb where id = p_propuesta_id for update;
    if not found or v_p.estado not in ('pendiente', 'aprobada') then
        raise exception 'propuesta % no publicable', p_propuesta_id;
    end if;
    if jsonb_typeof(p_fragmentos) <> 'array' or jsonb_array_length(p_fragmentos) = 0 then
        raise exception 'fragmentos vacíos';
    end if;

    -- 3. Los fragmentos son texto literal del borrador revisado (sin el pie).
    v_md := split_part(v_p.borrador_md, E'\n---\n', 1);
    for v_f in select * from jsonb_array_elements(p_fragmentos) loop
        v_seccion := v_f->>'seccion';
        v_texto   := coalesce(v_f->>'texto', '');
        if v_seccion not in ('resumen', 'sintoma', 'causa', 'pasos', 'verificacion') or length(v_texto) = 0 then
            raise exception 'fragmento inválido: %', v_seccion;
        end if;
        if v_seccion = 'resumen' then
            if left(v_texto, length(v_p.titulo)) <> v_p.titulo then
                raise exception 'el resumen no corresponde al título de la propuesta';
            end if;
        elsif strpos(v_md, v_texto) = 0 then
            raise exception 'la sección % no es texto del borrador revisado', v_seccion;
        end if;
    end loop;

    -- 4. contenido_md reconstruido solo con las secciones validadas.
    select '# ' || v_p.titulo || E'\n\n' || string_agg(
               '## ' || case f->>'seccion' when 'sintoma' then 'Síntoma' when 'causa' then 'Causa'
                                           when 'pasos' then 'Pasos' else 'Verificación' end
               || E'\n' || (f->>'texto'), E'\n\n'
               order by array_position(array['sintoma','causa','pasos','verificacion'], f->>'seccion'))
      into v_contenido
      from jsonb_array_elements(p_fragmentos) f
     where f->>'seccion' <> 'resumen';

    -- 5. Artículo: la corrección actualiza el existente (conserva receta y versiones); el faltante crea KB-SIM-NNN.
    if v_p.tipo = 'articulo_desactualizado' then
        v_id := v_p.articulo_id;
        update conocimiento.articulos
           set titulo = v_p.titulo, contenido_md = v_contenido, hash_contenido = md5(v_contenido),
               fecha_actualizacion = current_date, actualizado_en = now()
         where id = v_id and estado <> 'retirado';
        if not found then
            raise exception 'artículo % inexistente o retirado', v_id;
        end if;
        delete from conocimiento.kb_fragmentos where articulo_id = v_id and seccion <> 'receta';
    else
        perform pg_advisory_xact_lock(hashtext('conocimiento.articulos.id'));
        select 'KB-SIM-' || lpad((coalesce(max(substring(id from 8)::int), 0) + 1)::text, 3, '0')
          into v_id from conocimiento.articulos where id ~ '^KB-SIM-[0-9]{3}$';
        insert into conocimiento.articulos (id, titulo, categoria_id, fecha_actualizacion, estado, contenido_md,
                                            receta, hash_contenido)
        values (v_id, v_p.titulo, v_p.categoria_id, current_date, 'publicado', v_contenido,
                '{}'::jsonb, md5(v_contenido));
    end if;

    -- 6. Fragmentos (tsv es generado; la receta de diagnóstico la sigue definiendo P2/N2).
    for v_f in select * from jsonb_array_elements(p_fragmentos) loop
        v_vec := case when jsonb_typeof(v_f->'embedding') = 'array'
                      then (v_f->>'embedding')::public.vector else null end;
        insert into conocimiento.kb_fragmentos (articulo_id, seccion, orden, texto, categoria_id,
                                                versiones_aplicables, embedding, modelo_embedding, dimension,
                                                embebido_en)
        select v_id, v_f->>'seccion', coalesce((v_f->>'orden')::int, 0), left(v_f->>'texto', 4000),
               a.categoria_id, a.versiones_aplicables, v_vec,
               case when v_vec is null then null else p_modelo end,
               case when v_vec is null then null else public.vector_dims(v_vec) end,
               case when v_vec is null then null else now() end
          from conocimiento.articulos a where a.id = v_id;
    end loop;

    -- 7. Cierra la propuesta.
    update conocimiento.propuestas_kb
       set estado = 'publicada', revisor_id = p_revisor_id, revisado_en = now(),
           articulo_id = coalesce(articulo_id, v_id)
     where id = p_propuesta_id;
    return v_id;
end;
$$;

revoke all on function conocimiento.publicar_propuesta(bigint, text, jsonb, text) from public;
grant execute on function conocimiento.publicar_propuesta(bigint, text, jsonb, text) to app_rw;

-- Defensa en profundidad: app_rw solo cambia el estado de revisión de una propuesta, nunca su contenido.
revoke update on conocimiento.propuestas_kb from app_rw;
grant update (estado, revisor_id, comentario_revision, revisado_en) on conocimiento.propuestas_kb to app_rw;
```

Notas:
- La función no acepta fragmentos `receta`: un borrador nunca cambia la receta de diagnóstico.
- **El revisor no se autentica en la BD.** `p_revisor_id` lo envía el backend (identidad del directorio). La función
  comprueba que sea un revisor activo, pero no que sea quien llama: esa garantía la da el backend.
- Si P2 prefiere que el artículo nuevo quede en `borrador`, basta cambiar `'publicado'` en el `insert`.
- El backend ya llama a esta firma exacta (`app/rag/curaduria.py::publicar`). Si la función no existe, cae a
  `aprobada` sin error y el revisor ve «Reintentar publicación». Un error **dentro** de la función no se oculta.

## 2. Secuencia de incidentes masivos

La semilla inserta `INC-SIM-0001…` con id explícito y la secuencia queda atrás. Al final de la semilla:

```sql
select setval('operacion.incidentes_seq',
              coalesce((select max(substring(id from 9)::int) from operacion.incidentes_masivos), 0) + 1,
              false);
```

## 3. Idempotencia del lote del curador

El backend guarda la clave del grupo como prefijo de la justificación (`[clave=…] motivo`). El índice evita
duplicados aunque corran dos lotes a la vez:

```sql
create unique index if not exists propuestas_kb_clave_activa_uq
    on conocimiento.propuestas_kb ((substring(justificacion from '^\[clave=([^\]]+)\]')))
 where estado in ('pendiente', 'aprobada', 'publicada')
   and justificacion like '[clave=%';
```

## 4. Esquema `orquestador` (opcional)

Para guardar el estado a mitad de turno con `AsyncPostgresSaver` (`CHECKPOINTER=postgres`, ADR 0018). Las tablas las
crea LangGraph (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`).

```sql
create schema if not exists orquestador authorization app_rw;
revoke all on schema orquestador from public;
-- app_rw NO recibe nada nuevo sobre evaluacion; el esquema solo contiene el estado del grafo.
```

## 5. Re-embeber fragmentos sin vector

Si la publicación llega sin embeddings (Ollama caído), el fragmento queda con `embedding is null`. Basta con que el
script de vectores de P2 procese también:

```sql
select id, texto from conocimiento.kb_fragmentos where embedding is null;
```

## 6. Túnel con nombre

`cloudflared tunnel create caso5-bd` + un `config.yml` con `ingress: - hostname: bd.<dominio> service: tcp://localhost:5432`.
Así la dirección es fija y `DB_TUNEL_HOST` no cambia. La alternativa para la demo es correr todo en la máquina de P2
con `docker-compose.db.yml`.

---

## Verificación (cuando P2 lo aplique)

```powershell
docker compose exec api python -c "import psycopg; from app.config.ajustes import obtener_ajustes as a; c=psycopg.connect(a().database_url); print(c.execute(\"select has_function_privilege('conocimiento.publicar_propuesta(bigint,text,jsonb,text)','execute')\").fetchone())"
```

Debe imprimir `(True,)`. Después, en la UI: Revisor de KB → «Ejecutar lote ahora» → «Publicar» en una propuesta
completa. El aviso debe decir «Publicado en la KB como KB-SIM-031».
