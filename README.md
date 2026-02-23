# MadaraMaster

**Secure File Destruction Tool — NIST SP 800-88 & DoD 5220.22-M**

> **Warning:** This tool permanently destroys data. Only use it on files you are authorized to delete. Always verify the target path before running.

---

## What it does

MadaraMaster overwrites files following recognized sanitization standards before deleting them, making recovery with conventional forensic tools impossible.

**Automatic storage detection** — distinguishes HDD, SSD and NVMe on Linux, Windows and macOS and adjusts the strategy accordingly. Multiple passes on SSDs make no sense; the controller's wear leveling redistributes writes anyway, so one random pass is sufficient per NIST SP 800-88.

**Async engine** — built with `aiofiles` and adaptive buffers (50 MB for SSD, 10 MB for HDD).

**Entropy verification** — optional `--verify` flag. Samples random blocks after wiping and calculates Shannon entropy; if it falls below 7.0 bits/byte the operation is marked as failed.

**Audit log** — every operation is recorded in `madara_audit.jsonl` (JSON Lines) with pre-wipe SHA-256, UTC timestamps, user, hostname and result. Append-only.

**Interactive session** — argumentless mode where you can drag files into the terminal, queue them and wipe them all at once.

---

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/jaimefg1888/MadaraMaster
cd MadaraMaster
pip install -r requirements.txt
```

Dependencies: `typer`, `rich`, `aiofiles`.

---

## Usage

### Interactive mode

```bash
python madara.py
```

Select language at startup, then drag files or type paths. Press Enter with a non-empty queue to start wiping.

### CLI

```bash
python madara.py wipe secret.pdf
python madara.py wipe /path/to/directory
python madara.py wipe secret.pdf --confirm
python madara.py wipe /path --dry-run
python madara.py wipe data.pdf --standard purge --verify
python madara.py wipe data.pdf --log-path /var/log/madara_audit.jsonl
```

| Option | Alias | Description |
|--------|-------|-------------|
| `--confirm` | `-y` | Skip confirmation |
| `--dry-run` | `-n` | Preview without wiping |
| `--standard` | `-s` | `clear`, `purge` or `dod` |
| `--verify` | `-v` | Verify entropy after wipe |
| `--log-path` | `-l` | Custom path for audit log |

---

## Standards

| Standard | Passes | When to use |
|----------|--------|-------------|
| `clear` | 1 | General use, non-critical data |
| `purge` | 3 + verify | Sensitive data |
| `dod` | 3 | Same as purge, DoD 5220.22-M compatibility |

On SSDs, one random pass is always applied regardless of the chosen standard.

---

## How the wipe works

**HDDs:**
1. Pass 1 — overwrite with `0x00`
2. Pass 2 — overwrite with `0xFF`
3. Pass 3 — cryptographic random bytes via `os.urandom()`
4. `fsync()` after each pass to force physical write
5. Timestamps reset to epoch 0, random inode rename, deletion

**SSDs/NVMe:**
1. Single pass of cryptographic random bytes
2. `fsync()` and deletion

The entropy check (`--verify`) samples 20 random 4 KB blocks and verifies the average exceeds 7.0 bits/byte.

---

## Audit log

Each operation appends a line to `madara_audit.jsonl`:

```json
{
  "timestamp": "2026-02-15T21:30:00+00:00",
  "file": "/path/to/file.pdf",
  "size_bytes": 204800,
  "sha256_before": "a3f5...",
  "standard": "purge",
  "passes": 3,
  "verified": true,
  "duration_sec": 1.23,
  "user": "jaimefg1888",
  "hostname": "my-machine",
  "success": true,
  "error": null,
  "strategy": "HDD (purge)"
}
```

---

## Windows context menu

```bash
# requires CMD as Administrator
python madara.py install-right-click
```

Adds "Wipe with MadaraMaster" to the right-click menu on any file.

---

## Docker

```bash
docker build -t madaramaster .
docker run --rm -v /path/to/directory:/data madaramaster wipe /data/secret.pdf --confirm
```

---

## Project structure

```
MadaraMaster/
├── madara.py           # CLI + live dashboard
├── wiper.py            # synchronous engine
├── wiper_async.py      # async engine
├── storage.py          # storage detection
├── audit.py            # forensic log
├── utils.py            # utilities
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## FAQ

**Is 1 pass enough on SSD?**
Yes. NIST SP 800-88 Rev. 1 confirms it. Multiple passes add no real security on flash and shorten the device's lifespan.

**Can anything be recovered afterwards?**
No, if the operation completed successfully. The SHA-256 in the log is from the original file, before any overwriting.

**Does it work on encrypted filesystems?**
Yes. MadaraMaster operates directly on the file regardless of the underlying filesystem encryption.

**What if I interrupt it mid-way?**
The file will be partially overwritten. Run the wipe again on it.

---

## License

MIT. See the LICENSE file.

This software is provided for authorized data sanitization use only. The author takes no responsibility for misuse or data loss from incorrect usage.

---

**Author:** jaimefg1888

---
---

# MadaraMaster

**Herramienta de Destrucción Segura de Archivos — NIST SP 800-88 y DoD 5220.22-M**

> **Aviso:** Esta herramienta destruye datos de forma permanente. Úsala solo con archivos que estés autorizado a eliminar. Verifica siempre la ruta antes de ejecutar.

---

## Qué hace

MadaraMaster sobrescribe archivos siguiendo estándares de destrucción segura de datos reconocidos antes de eliminarlos, de forma que no puedan recuperarse con herramientas forenses convencionales.

**Detección automática de almacenamiento** — distingue HDD, SSD y NVMe en Linux, Windows y macOS y ajusta la estrategia en consecuencia. En SSDs no tiene sentido hacer múltiples pases; el wear leveling del controlador redistribuye las escrituras de todas formas, así que un pase aleatorio es suficiente según NIST SP 800-88.

**Motor async** — escrito con `aiofiles` y buffers adaptivos (50 MB en SSD, 10 MB en HDD).

**Verificación de entropía** — flag `--verify` opcional. Muestrea bloques aleatorios del fichero tras el borrado y calcula entropía Shannon; si está por debajo de 7.0 bits/byte lo marca como fallido.

**Log de auditoría** — cada operación queda registrada en `madara_audit.jsonl` (JSON Lines) con SHA-256 pre-borrado, timestamps UTC, usuario, hostname y resultado. Append-only.

**Sesión interactiva** — modo sin argumentos donde puedes arrastrar archivos a la terminal, hacer cola y borrarlos todos de golpe.

---

## Instalación

Requiere Python 3.10+.

```bash
git clone https://github.com/jaimefg1888/MadaraMaster
cd MadaraMaster
pip install -r requirements.txt
```

Dependencias: `typer`, `rich`, `aiofiles`.

---

## Uso

### Modo interactivo

```bash
python madara.py
```

Selecciona idioma al arrancar, luego arrastra archivos o escribe rutas. Pulsa Enter con la cola llena para iniciar el borrado.

### CLI

```bash
python madara.py wipe secreto.pdf
python madara.py wipe /ruta/directorio
python madara.py wipe secreto.pdf --confirm
python madara.py wipe /ruta --dry-run
python madara.py wipe datos.pdf --standard purge --verify
python madara.py wipe datos.pdf --log-path /var/log/madara_audit.jsonl
```

| Opción | Alias | Descripción |
|--------|-------|-------------|
| `--confirm` | `-y` | Saltar confirmación |
| `--dry-run` | `-n` | Vista previa sin borrar |
| `--standard` | `-s` | `clear`, `purge` o `dod` |
| `--verify` | `-v` | Verificar entropía post-borrado |
| `--log-path` | `-l` | Ruta para el log de auditoría |

---

## Estándares soportados

| Estándar | Pases | Cuándo usarlo |
|----------|-------|---------------|
| `clear` | 1 | Uso general, datos no críticos |
| `purge` | 3 + verificación | Datos sensibles |
| `dod` | 3 | Igual que purge, compatibilidad DoD 5220.22-M |

En SSDs siempre se aplica 1 pase aleatorio independientemente del estándar elegido.

---

## Cómo funciona el borrado

**HDDs:**
1. Pase 1 — sobrescritura con `0x00`
2. Pase 2 — sobrescritura con `0xFF`
3. Pase 3 — bytes aleatorios de `os.urandom()`
4. `fsync()` tras cada pase para forzar escritura física
5. Timestamps reseteados a epoch 0, renombrado aleatorio del inodo, eliminación

**SSDs/NVMe:**
1. Un único pase de bytes aleatorios criptográficos
2. `fsync()` y eliminación

La verificación de entropía (`--verify`) muestrea 20 bloques aleatorios de 4 KB y comprueba que la media supere 7.0 bits/byte.

---

## Log de auditoría

Cada operación genera una línea en `madara_audit.jsonl`:

```json
{
  "timestamp": "2026-02-15T21:30:00+00:00",
  "file": "/ruta/al/archivo.pdf",
  "size_bytes": 204800,
  "sha256_before": "a3f5...",
  "standard": "purge",
  "passes": 3,
  "verified": true,
  "duration_sec": 1.23,
  "user": "jaimefg1888",
  "hostname": "mi-equipo",
  "success": true,
  "error": null,
  "strategy": "HDD (purge)"
}
```

---

## Menú contextual Windows

```bash
# requiere CMD como Administrador
python madara.py install-right-click
```

Añade "Wipe with MadaraMaster" al menú contextual de cualquier archivo.

---

## Docker

```bash
docker build -t madaramaster .
docker run --rm -v /ruta/directorio:/data madaramaster wipe /data/secreto.pdf --confirm
```

---

## Estructura del proyecto

```
MadaraMaster/
├── madara.py           # CLI + dashboard en vivo
├── wiper.py            # motor síncrono
├── wiper_async.py      # motor asíncrono
├── storage.py          # detección de almacenamiento
├── audit.py            # log forense
├── utils.py            # utilidades
├── requirements.txt
├── Dockerfile
└── README.md
```

---

## FAQ

**¿Es suficiente 1 pase en SSD?**
Sí. NIST SP 800-88 Rev. 1 lo confirma. Varios pases no añaden seguridad real en flash y acortan la vida del dispositivo.

**¿Se puede recuperar algo después?**
No, si se completó con éxito. El SHA-256 en el log es del archivo original, antes de cualquier sobrescritura.

**¿Funciona en sistemas de archivos cifrados?**
Sí. MadaraMaster opera sobre el archivo directamente, independientemente del cifrado del sistema de archivos subyacente.

**¿Qué pasa si lo interrumpo a mitad?**
El archivo quedará parcialmente sobrescrito. Vuelve a ejecutar el borrado sobre él.

---

## Licencia

MIT. Consulta el archivo LICENSE.

El software se proporciona para uso autorizado de destrucción segura de datos de datos. El autor no se hace responsable del mal uso ni de pérdida de datos por uso incorrecto.

---

**Autor:** jaimefg1888
