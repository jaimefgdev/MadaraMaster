# 🧹 MadaraMaster

**DoD 5220.22-M Compliant Secure File Sanitization Tool**

> **⚠️ LEGAL DISCLAIMER / AVISO LEGAL:**
> This tool **permanently and irrecoverably destroys data**. Use only on files you are authorized to delete. The authors accept no liability for data loss. Always verify your target path and make backups before use.
>
> Esta herramienta **destruye datos de forma permanente e irrecuperable**. Úsala solo con archivos que estés autorizado a eliminar. Los autores no aceptan responsabilidad por pérdida de datos. Verifica siempre la ruta destino y haz copias de seguridad antes de usar.

---

## 📑 Table of Contents / Índice

- [What is DoD 5220.22-M? / ¿Qué es DoD 5220.22-M?](#what-is-dod-522022-m)
- [Features / Características](#features)
- [Installation / Instalación](#installation)
- [Usage / Uso](#usage)
- [Docker](#docker)
- [Data Recovery / Recuperación de Datos](#data-recovery--irrecoverability)
- [Project Structure / Estructura](#project-structure)

---

## What is DoD 5220.22-M?

### 🇬🇧 English

The **DoD 5220.22-M** standard, established by the U.S. Department of Defense, defines a method for securely sanitizing digital storage media. It ensures that data cannot be recovered by forensic tools or laboratory techniques.

**The standard specifies 3 overwrite passes:**

| Pass | Data Written | Purpose |
|------|-------------|---------|
| **1** | All zeros (`\x00`) | Eliminates the original magnetic charge patterns |
| **2** | All ones (`\xFF`) | Inverts the magnetic domain, destroying residual traces |
| **3** | Cryptographic random bytes | Replaces any remaining statistical patterns |

After three passes, the original data's magnetic signature is effectively destroyed. Even advanced techniques like **Magnetic Force Microscopy (MFM)** cannot reliably distinguish the original data from the overwritten noise.

### 🇪🇸 Español

El estándar **DoD 5220.22-M**, establecido por el Departamento de Defensa de EE.UU., define un método para sanitizar medios de almacenamiento digital de forma segura. Garantiza que los datos no puedan ser recuperados por herramientas forenses ni técnicas de laboratorio.

**El estándar especifica 3 pases de sobrescritura:**

| Pase | Datos Escritos | Propósito |
|------|---------------|-----------|
| **1** | Ceros (`\x00`) | Elimina los patrones magnéticos originales |
| **2** | Unos (`\xFF`) | Invierte el dominio magnético, destruyendo trazas residuales |
| **3** | Bytes aleatorios criptográficos | Reemplaza cualquier patrón estadístico restante |

Tras tres pases, la firma magnética original es efectivamente destruida. Incluso técnicas avanzadas como la **Microscopía de Fuerza Magnética (MFM)** no pueden distinguir los datos originales del ruido sobrescrito.

---

## Features

| Feature | Description / Descripción |
|---------|--------------------------|
| 🔴 **DoD 5220.22-M** | Standard-compliant 3-pass overwrite with fsync |
| 🛡️ **Anti-Forensics** | Scrubs timestamps and renames files before deletion |
| 📂 **Recursive** | Wipes entire directories including all subdirectories |
| 📊 **Rich Progress** | Real-time per-file, per-pass progress bars |
| 🔍 **Dry Run** | Preview mode to see what would be deleted |
| ⚠️ **Confirmation** | Requires explicit confirmation before wiping |
| 🐳 **Docker** | Containerized execution for isolation |
| ❌ **Error Resilient** | Continues on locked/permission-denied files |

---

## Installation

```bash
# Clone
git clone https://github.com/jaimefg1888/MadaraMaster
cd madaramaster

# Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Interactive Session / Sesión Interactiva (Recommended)
```bash
python madara.py
```

On startup, the tool will ask you to choose a language:

```
Select Language / Seleccione Idioma [1: EN | 2: ES]:
```

> Press **1** (or Enter) for English, **2** for Spanish. All prompts, progress labels, and summary messages will appear in your chosen language.
>
> Pulse **1** (o Enter) para inglés, **2** para español. Todos los mensajes, etiquetas de progreso y resúmenes se mostrarán en el idioma seleccionado.

💡 Pro Tip: In interactive mode, just drag and drop the file into the terminal window and press Enter.

💡 Consejo Pro: En modo interactivo, simplemente arrastra y suelta el archivo en la terminal y pulsa Enter.


### Wipe a single file / Borrar un archivo
```bash
python madara.py wipe secret_document.pdf
```

### Wipe an entire directory / Borrar un directorio completo
```bash
python madara.py wipe ./confidential-folder/
```

### Skip confirmation / Saltar confirmación
```bash
python madara.py wipe ./old-data/ --confirm
```

### Dry run — preview only / Solo previsualizar
```bash
python madara.py wipe ./sensitive/ --dry-run
```

### Show help / Mostrar ayuda
```bash
python madara.py --help
python madara.py wipe --help
```

---

## Docker

```bash
# Build
docker build -t madaramaster .

# Wipe files inside /data (mount your directory)
docker run --rm -it -v /path/to/files:/data madaramaster wipe /data --confirm
```

---

## Data Recovery & Irrecoverability

### 🇬🇧 Why Recovery is Impossible After MadaraMaster

This section explains **why data sanitized with DoD 5220.22-M is irrecoverable**, even with professional forensic tools.

#### How Data Normally Gets "Deleted"

When you delete a file normally (pressing Delete, using `rm`, emptying the Recycle Bin), the operating system only removes the **directory entry** — the pointer to the file. The actual data remains physically on the disk platters or flash cells until it is eventually overwritten by new data. This is why tools like **Recuva**, **PhotoRec**, **Autopsy**, and **EnCase** can often recover "deleted" files — the bytes are still there.

#### What MadaraMaster Does Differently

MadaraMaster does NOT simply delete the file pointer. It **physically overwrites every byte of the file's data on disk**, three times:

1. **Pass 1 (Zeros):** Every byte of the file is replaced with `0x00`. The original magnetic charge pattern on the disk platter is replaced with a uniform zero field. At this point, the original data is already gone from the storage medium.

2. **Pass 2 (Ones):** Every byte is then replaced with `0xFF`. This inverts the magnetic domain, ensuring that no residual magnetization from the original data or the first pass can be detected. This defeats techniques that attempt to read "ghost" signals between overwrite layers.

3. **Pass 3 (Random):** Finally, every byte is overwritten with cryptographically secure random data from `os.urandom()`. This destroys any statistical pattern that might remain, making it impossible to determine what the previous values were, even through electron microscopy.

4. **fsync():** After each pass, MadaraMaster calls `os.fsync()` on the file descriptor, forcing the operating system to flush all buffered writes to the physical disk. This guarantees the overwrites reach the actual storage medium and are not sitting in an OS cache.

5. **Metadata Scrub:** Before deletion, the file's timestamps are reset to epoch (1970-01-01) and the filename is changed to a random string. This prevents forensic timeline analysis and directory entry recovery.

#### Why Forensic Software Cannot Recover This Data

| Tool | Capability | Against MadaraMaster |
|------|-----------|---------------------|
| **Recuva** | Recovers files from deleted directory entries | ❌ Data is overwritten, not just unlinked |
| **PhotoRec** | Carves files by signature from raw disk | ❌ Original signatures destroyed by 3 passes |
| **Autopsy/Sleuthkit** | Timeline analysis + file carving | ❌ Timestamps scrubbed, data overwritten |
| **EnCase** | Professional forensic suite | ❌ Cannot reconstruct overwritten sectors |
| **MFM/STM** | Electron microscopy on disk platters | ❌ 3 passes exceed microscopy detection limits |

> **The Peter Gutmann Study (1996):** Gutmann's seminal paper suggested that older magnetic media might retain traces after a single overwrite. However, modern research has conclusively shown that **a single overwrite is sufficient** on modern hard drives, and **three passes provide an extreme margin of safety**. No peer-reviewed study has demonstrated reliable recovery after even a single proper overwrite on post-2001 hard drive technology. (Source: NIST SP 800-88 Rev. 1)

### 🇪🇸 Por Qué la Recuperación es Imposible

#### Cómo se "borran" normalmente los datos

Cuando eliminas un archivo normalmente (Papelera, `rm`, Supr), el sistema operativo solo elimina el **puntero** al archivo. Los datos reales permanecen físicamente en el disco hasta que son sobrescritos por datos nuevos. Por eso herramientas como **Recuva**, **PhotoRec** o **Autopsy** pueden recuperar archivos "eliminados".

#### Qué hace MadaraMaster de forma diferente

MadaraMaster **sobrescribe físicamente cada byte del archivo** tres veces:

1. **Pase 1 (Ceros):** Cada byte se reemplaza con `0x00`. El patrón magnético original desaparece.
2. **Pase 2 (Unos):** Cada byte se reemplaza con `0xFF`. Invierte el dominio magnético, destruyendo trazas residuales.
3. **Pase 3 (Aleatorio):** Cada byte se sobrescribe con datos aleatorios criptográficos (`os.urandom()`). Destruye cualquier patrón estadístico restante.
4. **fsync():** Tras cada pase se fuerza la escritura física al disco.
5. **Limpieza de metadatos:** Timestamps reseteados y nombre de archivo aleatorizado.

> **⚠️ ADVERTENCIA CRÍTICA:** Antes de usar MadaraMaster, **ASEGÚRATE** de tener copias de seguridad de todo lo que necesites. Una vez ejecutada la herramienta, **NO HAY FORMA** de recuperar los datos. Ni nosotros, ni ningún laboratorio forense, ni ningún software puede deshacer la sobrescritura de tres pases.

---

## Project Structure

```
madaramaster/
├── wiper.py          # DoD 5220.22-M wipe engine (3-pass, fsync, metadata scrub)
├── madara.py         # Typer CLI + Rich UI (banner, progress, interactive session)
├── requirements.txt  # Python dependencies
├── Dockerfile        # Containerized execution (non-root)
├── deploy.py         # Git push automation
└── README.md         # This file (bilingual)
```

---

## License

MIT License — See [LICENSE](LICENSE) for details.

---

**Built with** 🐍 Python • ⌨️ Typer • 📊 Rich • 🐳 Docker
