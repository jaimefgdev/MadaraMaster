# MadaraMaster v4.0

Herramienta de borrado seguro de archivos. Implementa NIST SP 800-88 Rev. 1 y DoD 5220.22-M.

> **Aviso:** Esta herramienta destruye datos de forma permanente. Úsala solo con archivos que estés autorizado a eliminar. Verifica siempre la ruta antes de ejecutar.

---

## Novedades en v4.0

Reescritura completa respecto a v3. Los cambios principales:

**Detección automática de almacenamiento** — distingue HDD, SSD y NVMe en Linux, Windows y macOS, y ajusta la estrategia en consecuencia. En SSDs no tiene sentido hacer 3 pases; el wear leveling del controlador redistribuye las escrituras de todas formas, así que un pase aleatorio es suficiente según NIST SP 800-88.

**Motor async** — reescrito con `aiofiles` y buffers adaptivos (50 MB en SSD, 10 MB en HDD). En la práctica sale unas 3x más rápido en SSDs respecto a v3.

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
# borrar un archivo
python madara.py wipe secreto.pdf

# directorio completo
python madara.py wipe /ruta/directorio

# sin confirmación
python madara.py wipe secreto.pdf --confirm

# vista previa sin borrar nada
python madara.py wipe /ruta --dry-run

# 3 pases + verificación de entropía
python madara.py wipe datos.pdf --standard purge --verify

# log en ruta personalizada
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

## Estándares

| Estándar | Pases | Cuándo usarlo |
|----------|-------|---------------|
| `clear` | 1 | Uso general, datos no críticos |
| `purge` | 3 + verificación | Datos sensibles |
| `dod` | 3 | Igual que purge, por compatibilidad |

En SSDs siempre se hace 1 pase aleatorio independientemente del estándar elegido.

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

La verificación de entropía (flag `--verify`) muestrea 20 bloques aleatorios de 4 KB y comprueba que la media supere 7.0 bits/byte. Si no lo supera, la operación se marca como fallida en el log.

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
├── wiper.py            # motor síncrono (compatibilidad v3)
├── wiper_async.py      # motor asíncrono v4.0
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

El software se proporciona para uso autorizado de sanitización de datos. El autor no se hace responsable del mal uso ni de pérdida de datos por uso incorrecto.

---

**Autor:** jaimefg1888 · **Versión:** 4.0.0 · **Año:** 2026
