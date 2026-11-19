import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Vista reservada para una feature posterior (ver docs/PLAN_FEATURES.md). */
export function VistaPendiente({ titulo, feature, descripcion }: { titulo: string; feature: string; descripcion: string }) {
  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>
          <h1>{titulo}</h1>
        </CardTitle>
        <CardDescription>Se habilita en {feature}.</CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">{descripcion}</CardContent>
    </Card>
  );
}
