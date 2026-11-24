# Security policy

## Versiones soportadas

Solo la rama `main` y la última release reciben fixes de seguridad.

## Reportar una vulnerabilidad

No abras un issue público con un bypass del guard, una clave o un target real.
Usá [GitHub Security Advisories](https://github.com/Davoassassin27/kensei/security/advisories/new)
o contactá a [@Davoassassin27](https://github.com/Davoassassin27) en privado.

Incluí:

- versión de Kensei y de Ollama;
- sistema operativo y versión de Python;
- un `scope.yaml` mínimo que reproduzca el problema, sin datos sensibles;
- el comando o tool-call que evita el guard, y el resultado esperado.

## Alcance

Se consideran vulnerabilidades:

- evasión del bloqueo de comandos destructivos;
- ejecución de red fuera del scope autorizado;
- escritura fuera del workspace permitido;
- fuga de secretos en logs, auditoría o prompts;
- inyección de prompt que termine en una acción destructiva sin confirmación.

No se consideran vulnerabilidades:

- que el modelo proponga un comando peligroso: el guard debe bloquearlo;
- que el scope global permita targets globales: es una decisión del operador;
- resultados incorrectos del modelo sin impacto en el guard.

## Uso autorizado

Kensei es una herramienta de operación y seguridad ofensiva. Usala solo contra
sistemas propios, laboratorios, CTFs o engagements con autorización escrita.
Los maintainers no aceptan reportes generados atacando terceros.
