# Kensei — marca oficial

**Kensei** es el SLM de terminal de Ronin: un operador local para diagnosticar, ejecutar y verificar tareas dentro de un alcance autorizado. Su marca es el **Mon rojo (B)**.

Kensei no es el OS: es la herramienta. Comparte el ADN de Ronin (perfil, kasa, trigo) y se diferencia por el **bermellón**.

## Archivos

### `logo/`

| Archivo | Fondo | Uso |
| --- | --- | --- |
| `kensei-mon.svg` | Oscuro / claro | **Mon oficial**: disco bermellón `#A63A2F`, perfil oro |
| `kensei-mon-mono.svg` | Una tinta | Disco tinta, perfil blanco |
| `kensei-mon-light.svg` | Claro | Disco hueso, perfil tinta |
| `kensei-mon-dark.svg` | Oscuro | Disco casi negro, perfil oro (para UI oscura) |
| `kensei-profile-gold.svg` | Transparente | Perfil oro con detalles bermellón, para terminal/TUI |

`_source-kensei-mon.svg` es trazabilidad; no usar en producción.

### `icons/`

- `kensei-app-icon.svg` — icono de app (tile bermellón con perfil oro).
- `kensei-favicon.svg` / `favicon.svg`.
- `favicon.ico`, `favicon-16.png`, `favicon-32.png`, `favicon-48.png`.
- `apple-touch-icon.png`, `icon-192.png`, `icon-512.png`, `maskable-512.png`.
- `site.webmanifest`, `head-snippet.html`.

### `png/`

Exports a 1024 px de los SVG principales, fondo transparente.

## Paleta

| Token | Hex | Uso |
| --- | --- | --- |
| Vermilion | `#A63A2F` | Disco, acento de Kensei |
| Gold | `#E6C384` | Perfil, texto de acento |
| Ink | `#111111` | Texto, detalles |
| Bone | `#F2EFE7` | Fondo claro |
| Near-black | `#141414` | UI oscura |

El oro sobre bermellón funciona para gráfica grande; para texto pequeño usar hueso/blanco.

## Uso

- **CLI / terminal:** `kensei-profile-gold.svg` sobre fondo oscuro; el perfil sin disco se integra al prompt o al splash.
- **Docs / README / web:** `kensei-mon.svg` o `icons/kensei-app-icon.svg`.
- **Favicon / app:** `icons/favicon.ico`, `icons/icon-192.png`, `icons/icon-512.png`.
- **Una tinta:** `kensei-mon-mono.svg`.
- **No usar el mon rojo para Ronin** ni el mon oscuro de Ronin para Kensei, salvo co-branding explícito.

### Tamaños mínimos

- Mon: **24 px** digital, **10 mm** impresión.
- Perfil sin disco: **32 px** digital (el trigo es el primer detalle que se pierde).
- Favicon: `favicon.ico` / `favicon.svg`.

### Espacio libre

Al menos **1/4 del diámetro del mon** libre alrededor. En el perfil sin disco, 1/4 de la altura del perfil.

## SVG y motion

IDs disponibles:

`mark`, `disc`, `face`, `hat`, `wheat`, `grain`, `awn`, `band`, `eye`, `collar`.

Para el CLI, una animación sutil del `wheat` (±1.5°) y un `eye` que parpadea una vez al iniciar es suficiente. En la app icon no animar; el sello debe quedar quieto.

Los trazos de `wheat`, `band`, `collar` y `awn` están como stroke. Expandirlos a contornos para print/embroidery.

## Tipografía recomendada

- CLI / terminal: **Cascadia Code** o **JetBrains Mono** (monoespaciada).
- Docs / web: **IBM Plex Sans** o **Inter**.
- No están incluidas; son recomendaciones.

## Relación con Ronin

Kensei hereda el perfil de Ronin. La jerarquía es:

```
Ronin (OS)  ──►  Kensei (herramienta)
```

En una pieza de co-branding, Ronin va primero y Kensei después; el mon rojo no debe competir con el mon oscuro de Ronin. Si hay duda, usar solo el mon de Ronin y el nombre Kensei en tipografía.

## Origen

Perfil basado en una silueta de **dominio público (CC0)** del Met Museum, adaptada con kasa, trigo y busto. La referencia visual del usuario no se copió.

Fuente: [The Met — Silhouette of a man in profile to the right (CC0)](https://commons.wikimedia.org/wiki/File:Silhouette_of_a_man_in_profile_to_the_right_Met_DP887354.jpg).

## Licencia

Los assets oficiales de `brand/` se publican bajo **CC BY 4.0**. Atribución: "Kensei — https://github.com/Davoassassin27/kensei". Ver [`LICENSE-DOCS`](../LICENSE-DOCS) y [`NOTICE`](../NOTICE).
