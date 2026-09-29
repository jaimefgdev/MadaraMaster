## 🇬🇧 English

# 🧹 MadaraMaster

Secure file destruction tool. MadaraMaster overwrites files following NIST SP 800-88 and DoD 5220.22-M standards before deleting them, making recovery with conventional forensic tools impossible.

---

## Features

- **Automatic storage detection** — distinguishes HDD, SSD, and NVMe on Linux, Windows, and macOS and adjusts the strategy accordingly.
- **Async engine** built with `aiofiles` and adaptive buffers (50 MB for SSD/NVMe, 10 MB for HDD).
- **Direct I/O** — bypasses the OS page cache (`O_DIRECT | O_SYNC` on Linux; `FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH` on Windows) to ensure wiped data is never silently re-cached.
- **Slack space destruction** — every pass covers the file rounded up to a whole cluster, so the gap between EOF and the cluster boundary is overwritten too.
- **ADS destruction** (Windows only) — enumerates and wipes every Alternate Data Stream via `FindFirstStreamW` / `FindNextStreamW`.
- **Inode metadata scrubbing** — zeros all MAC timestamps and performs 3–5 renames with variable-length names to overwrite MFT / ext4 journal entries.
- **Optional `--verify` flag** — re-reads the file after the last pass and compares it with the SHA-256 of what was written; on mismatch the operation fails and the file is **not** deleted.
- **Safety checks** — symlinks and junctions are never followed (only the link is removed), non-regular files are skipped, files with several hard links are refused unless `--allow-hardlinks` is given, and protected targets (filesystem roots, your home directory, system directories, mount points) are refused unless `--allow-dangerous-target` is given. Wiping a directory asks you to type its name.
- **Audit log** — every operation is recorded as JSON Lines with UTC timestamps, user, hostname and result, in a private per-user file (`~/.local/state/madaramaster/audit.jsonl` on Linux, `~/Library/Logs/MadaraMaster/audit.jsonl` on macOS, `%LOCALAPPDATA%\MadaraMaster\audit.jsonl` on Windows). The pre-wipe SHA-256 is only recorded with `--hash`, because it lets anyone holding the log confirm what the file contained. `--no-log` disables the log.
- **Interactive session** — argumentless mode where you can drag files into the terminal, queue them, and wipe them all at once. Paths with spaces work with or without quotes; queuing a directory requires typing `WIPE` to confirm.

## Requirements

- Python 3.10+
- `typer >= 0.9.0`
- `rich >= 13.7.0`
- `aiofiles >= 23.2.1`

## Setup

```bash
git clone https://github.com/jaimefg1888/MadaraMaster
cd MadaraMaster
pip install -r requirements.txt
```

## Run it

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
python madara.py wipe data.pdf --log-path ~/madara_audit.jsonl
```

### Options

| Option | Alias | Description |
|--------|-------|-------------|
| `--confirm` | `-y` | Skip confirmation prompt |
| `--dry-run` | `-n` | Preview targets without wiping |
| `--standard` | `-s` | `clear`, `purge`, or `dod` |
| `--verify` | `-v` | Re-read and compare after wiping; keep the file on mismatch |
| `--log-path` | `-l` | Custom path for the audit log |
| `--no-log` | | Do not write an audit log |
| `--hash` | | Record each file's pre-wipe SHA-256 in the audit log |
| `--trim` | | After the batch, send one TRIM per filesystem (SSD/NVMe, Linux only) |
| `--allow-hardlinks` | | Also wipe files with several hard links (destroys the data of every name) |
| `--allow-dangerous-target` | | Allow protected targets (root, home, system dirs, mount points) |

### Standards

| Standard | Passes | When to use |
|----------|--------|-------------|
| `clear` | 1 | General use, non-critical data |
| `purge` | 3 + verify | Sensitive data |
| `dod` | 3 | DoD 5220.22-M compatibility |

`purge` always verifies after wiping, even without `--verify`.

On SSDs and NVMe drives, one cryptographic-random pass is always applied regardless of the chosen standard. Overwriting files on flash **cannot** guarantee NIST SP 800-88 *Purge* (wear-leveling and over-provisioning keep old copies out of reach); the tool warns about this when `purge` or `dod` is used on flash. Use full-disk encryption or the drive's own secure erase for that.

## Project structure

```
MadaraMaster/
├── madara.py           # CLI entry point + live dashboard
├── wiper.py            # Synchronous wipe engine (DoD 5220.22-M)
├── wiper_async.py      # Async wipe engine (Direct I/O, ADS, slack space)
├── storage.py          # Storage-type detection (Linux sysfs / Windows ctypes / macOS diskutil)
├── trim.py             # TRIM/Discard dispatch (Linux FITRIM / Windows DMDSA)
├── audit.py            # Forensic audit logger (JSON Lines)
├── utils.py            # Formatting utilities
├── requirements.txt
├── Dockerfile
└── README.md
```

## License

MIT. See the LICENSE file.

This software is provided for authorized data sanitization use only. The author takes no responsibility for misuse or data loss from incorrect usage.

---

## 🇪🇸 Español

# 🧹 MadaraMaster

Herramienta de destrucción segura de archivos. MadaraMaster sobrescribe archivos siguiendo los estándares NIST SP 800-88 y DoD 5220.22-M antes de eliminarlos, de forma que no puedan recuperarse con herramientas forenses convencionales.

---

## Características

- **Detección automática de almacenamiento** — distingue HDD, SSD y NVMe en Linux, Windows y macOS y ajusta la estrategia en consecuencia.
- **Motor async** con `aiofiles` y buffers adaptativos (50 MB en SSD/NVMe, 10 MB en HDD).
- **Direct I/O** — evita la caché de páginas del SO (`O_DIRECT | O_SYNC` en Linux; `FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH` en Windows) para garantizar que los datos borrados no queden en RAM.
- **Destrucción del slack space** — cada pase cubre el fichero redondeado al clúster, así que el espacio entre EOF y el límite del clúster también se sobrescribe.
- **Destrucción de ADS** (solo Windows) — enumera y machaca cada Alternate Data Stream mediante `FindFirstStreamW` / `FindNextStreamW`.
- **Limpieza de metadatos de inodo** — pone a cero todos los timestamps MAC y realiza 3–5 renombrados con nombres de longitud variable para machacar entradas de la MFT / journal ext4.
- **Flag `--verify` opcional** — relee el fichero tras el último pase y lo compara con el SHA-256 de lo escrito; si no coincide, la operación falla y el fichero **no** se elimina.
- **Salvaguardas** — los enlaces simbólicos y junctions nunca se siguen (solo se elimina el enlace), los ficheros no regulares se omiten, los ficheros con varios enlaces duros se rechazan salvo con `--allow-hardlinks`, y los objetivos protegidos (raíces de sistemas de archivos, tu HOME, directorios del sistema, puntos de montaje) se rechazan salvo con `--allow-dangerous-target`. Para borrar un directorio hay que escribir su nombre.
- **Log de auditoría** — cada operación queda registrada en JSON Lines con timestamps UTC, usuario, hostname y resultado, en un fichero privado del usuario (`~/.local/state/madaramaster/audit.jsonl` en Linux, `~/Library/Logs/MadaraMaster/audit.jsonl` en macOS, `%LOCALAPPDATA%\MadaraMaster\audit.jsonl` en Windows). El SHA-256 previo solo se guarda con `--hash`, porque permite a quien tenga el log confirmar qué contenía el fichero. `--no-log` desactiva el log.
- **Sesión interactiva** — modo sin argumentos donde puedes arrastrar archivos a la terminal, hacer cola y borrarlos todos de golpe. Las rutas con espacios funcionan con o sin comillas; si hay directorios en la cola hay que escribir `BORRAR` para confirmar.

## Requisitos

- Python 3.10+
- `typer >= 0.9.0`
- `rich >= 13.7.0`
- `aiofiles >= 23.2.1`

## Instalación

```bash
git clone https://github.com/jaimefg1888/MadaraMaster
cd MadaraMaster
pip install -r requirements.txt
```

## Ejecutar

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
python madara.py wipe datos.pdf --log-path ~/madara_audit.jsonl
```

### Opciones

| Opción | Alias | Descripción |
|--------|-------|-------------|
| `--confirm` | `-y` | Saltar confirmación |
| `--dry-run` | `-n` | Vista previa sin borrar |
| `--standard` | `-s` | `clear`, `purge` o `dod` |
| `--verify` | `-v` | Releer y comparar tras el borrado; conserva el fichero si no coincide |
| `--log-path` | `-l` | Ruta para el log de auditoría |
| `--no-log` | | No escribir log de auditoría |
| `--hash` | | Guardar en el log el SHA-256 previo de cada fichero |
| `--trim` | | Al terminar, enviar un TRIM por sistema de archivos (SSD/NVMe, solo Linux) |
| `--allow-hardlinks` | | Borrar también ficheros con varios enlaces duros (destruye los datos de todos sus nombres) |
| `--allow-dangerous-target` | | Permitir objetivos protegidos (raíz, HOME, directorios del sistema, puntos de montaje) |

### Estándares

| Estándar | Pases | Cuándo usarlo |
|----------|-------|---------------|
| `clear` | 1 | Uso general, datos no críticos |
| `purge` | 3 + verificación | Datos sensibles |
| `dod` | 3 | Compatibilidad DoD 5220.22-M |

`purge` siempre verifica tras el borrado, aunque no se pase `--verify`.

En SSD y NVMe siempre se aplica 1 pase aleatorio criptográfico independientemente del estándar elegido. Sobrescribir ficheros en flash **no** garantiza *Purge* de NIST SP 800-88 (el wear-leveling y el sobreaprovisionamiento conservan copias antiguas fuera de alcance); la herramienta avisa de ello al usar `purge` o `dod` en flash. Para eso, usa cifrado de disco completo o el borrado seguro de la propia unidad.

## Estructura del proyecto

```
MadaraMaster/
├── madara.py           # CLI + dashboard en vivo
├── wiper.py            # Motor síncrono (DoD 5220.22-M)
├── wiper_async.py      # Motor asíncrono (Direct I/O, ADS, slack space)
├── storage.py          # Detección de almacenamiento (sysfs / ctypes / diskutil)
├── trim.py             # Envío de TRIM/Discard (Linux FITRIM / Windows DMDSA)
├── audit.py            # Log forense (JSON Lines)
├── utils.py            # Utilidades de formato
├── requirements.txt
├── Dockerfile
└── README.md
```

## Licencia

MIT. Consulta el archivo LICENSE.

El software se proporciona para uso autorizado de destrucción segura de datos. El autor no se hace responsable del mal uso ni de pérdida de datos por uso incorrecto.
