"""User-visible strings (EN/ES) and the active interface language."""





# ─── i18n ────────────────────────────────────────────────────────────────────
# All user-visible strings are stored here to keep the rest of the code
# free of hard-coded text and to make adding new languages trivial.

LANG: dict[str, dict[str, str]] = {
    "EN": {
        "session_title": "Interactive Session Mode",
        "session_hint": "Drag files and press Enter (or type the path).",
        "session_exit_hint": "Type [bold]exit[/bold] or [bold]close[/bold] to quit.",
        "queue_count": "{n} file(s) queued",
        "queue_hint": "Add more files or press Enter to WIPE.",
        "session_prompt": "❱❱❱ ",
        "session_ended": "Session ended.",
        "session_goodbye": "👋 Session ended. See you later.",
        "continue_prompt": (
            "Press Enter to start a new wipe session or type [bold]exit[/bold] to quit..."
        ),
        "path_not_found": "✗ Path not found:",
        "target_not_found": "✗ Target not found:",
        "no_files_found": "⚠ No files found in:",
        "type_dir": "Directory (recursive)",
        "type_file": "Single file",
        "lbl_target": "Target",
        "lbl_type": "Type",
        "files_to_wipe": "Files to wipe",
        "total_data": "Total data",
        "method": "Method",
        "passes": "Passes",
        "pass_values": "1) Zeros  2) Ones  3) Random",
        "dry_run_title": "🔍 DRY RUN — no files will be modified:",
        "more_files": "...and {n} more files",
        "warning_title": "⚠ WARNING: THIS ACTION IS IRREVERSIBLE ⚠",
        "warning_body": (
            "All targeted files will be overwritten (1 to 3 passes depending on the\n"
            "standard and the storage type) and permanently deleted.\n"
            "[bold]Data CANNOT be recovered after this operation.[/]"
        ),
        "confirm_prompt": "  Are you sure you want to proceed?",
        "confirm_msg": "Are you sure? [y/N]: ",
        "op_cancelled": "Operation cancelled.",
        "starting": "Starting...",
        "preview_title": "📋 FILES TO DESTROY",
        "preview_name": "Name",
        "preview_size": "Size",
        "preview_type": "Type",
        "preview_total": "TOTAL",
        "dash_header": "🛡️  MADARA MASTER v{version}",
        "dash_file": "📁 File",
        "dash_algorithm": "🔒 Algorithm",
        "dash_status": "🔄 Status",
        "dash_pass": "Pass {i}/{n} — {pattern}...",
        "pat_zeros": "Overwriting with 0x00 (Zeros)",
        "pat_ones": "Overwriting with 0xFF (Ones)",
        "pat_random": "Overwriting with Random Bytes",
        "dash_algorithm_value": "{standard} · {n} pass(es)",
        "dash_scrubbing": "🧹 Scrubbing metadata & deleting...",
        "dash_progress": "📊 Global Progress",
        "dash_speed": "🚀 Speed",
        "dash_written": "💾 Effective Write",
        "dash_file_counter": "📂 File",
        "summary_title": "🧹 WIPE SUMMARY",
        "metric": "Metric",
        "value": "Value",
        "total_targeted": "Total Files Targeted",
        "files_wiped_ok": "Files Wiped Successfully",
        "files_failed": "Files Failed",
        "total_overwritten": "Total Bytes Overwritten",
        "effective_written": "Effective Data Written",
        "total_duration": "Total Duration",
        "avg_speed": "Average Write Speed",
        "errors_title": "⚠ Errors",
        "more_errors": "...and {n} more",
        "all_sanitized_one": "✔ {n} FILE OVERWRITTEN AND DELETED",
        "all_sanitized_many": "✔ {n} FILES OVERWRITTEN AND DELETED",
        "partial_wipe": "⚠ PARTIAL WIPE — {wiped} wiped, {failed} failed",
        "no_files_wiped": "✗ NO FILES WERE WIPED",
        "completion_msg": "DELETION COMPLETED SUCCESSFULLY",
        "wiped": "✔ Wiped",
        "version_desc": "Secure file sanitization (NIST SP 800-88 / DoD 5220.22-M patterns)",
        "version_license": "License: MIT — Authorized Use Only",
        "lbl_verify": "Verify",
        "lbl_audit_log": "Audit Log",
        "wfs_title": "Wipe Free Space",
        "wfs_hint": "Creating a temporary fill-file to defeat wear-leveling…",
        "wfs_filling": "Filling free space with zeros",
        "wfs_chunk": "Chunk",
        "wfs_enospc": "Disk full — all free space covered.",
        "wfs_syncing": "Syncing to physical media (fsync)…",
        "wfs_removing": "Removing fill-file…",
        "wfs_trim": "Sending TRIM to storage controller…",
        "wfs_trim_ok": "TRIM sent successfully.",
        "wfs_trim_skip": "TRIM skipped (not SSD/NVMe or insufficient permissions).",
        "wfs_done": "Free-space wipe complete.",
        "wfs_written": "Zeros written",
        "wfs_duration": "Duration",
        "wfs_error": "Error during free-space wipe",
        "wfs_dry": "DRY RUN — target directory:",
        "dangerous_target": "✗ Refusing to wipe a protected target:",
        "dangerous_target_hint": "Use --allow-dangerous-target only if you are absolutely sure.",
        "confirm_type_name": "  Type the directory name ({name}) to confirm",
        "wfs_cleanup_failed": "Could not remove the fill file — delete it manually:",
        "dangerous_target_interactive": (
            "Protected targets cannot be wiped from the interactive session."
        ),
        "confirm_word": "WIPE",
        "confirm_word_prompt": "Directories are queued. Type {word} to confirm: ",
        "ssd_purge_warning": (
            "The target is on an SSD/NVMe drive. Overwriting files cannot guarantee\n"
            "NIST 800-88 Purge on flash (wear-leveling, over-provisioning).\n"
            "For that, use full-disk encryption or the drive's own secure erase."
        ),
        "purge_forces_verify": "The purge standard always verifies after wiping.",
        "residue_title": "Copies may survive this wipe",
        "residue_cow_fs": (
            "Copy-on-write filesystem (btrfs, ZFS, APFS, ReFS…): overwrites go to new\n"
            "blocks, so the old data can stay on disk."
        ),
        "residue_network": (
            "Network location: the server may keep its own snapshots, caches or backups."
        ),
        "residue_cloud_sync": (
            "Cloud-synced folder (OneDrive, Dropbox, Google Drive, iCloud…): the cloud\n"
            "copy and its version history are not wiped. Delete them there too."
        ),
        "residue_data_journal": (
            "ext3/ext4 mounted with data=journal: file contents may remain in the journal."
        ),
        "residue_hint": "See the README's Limitations section for details.",
        "trims_sent": "TRIM sent",
        "lbl_hash": "Hash before wipe",
        "yes": "Yes",
        "no": "No",
        "interrupted": "Interrupted by the user.",
        "wipe_error": "Error during the wipe:",
        "lbl_storage": "Storage",
        "lbl_free_space": "Free space",
        "wfs_full_note": (
            "The disk will be full for a moment — this is expected.\n"
            "No existing file will be modified."
        ),
        "ctx_windows_only": "Error: only available on Windows.",
        "ctx_installed": "✔ Context-menu entry installed for the current user.",
        "ctx_command": "  Command: {cmd}",
        "ctx_error": "Error: {error}",
        "banner_subtitle": "NIST SP 800-88 · DoD 5220.22-M · v{version}",
    },
    "ES": {
        "session_title": "Modo Sesión Interactiva",
        "session_hint": "Arrastra archivos y pulsa Enter (o escribe la ruta).",
        "session_exit_hint": "Escribe [bold]salir[/bold] o [bold]cerrar[/bold] para salir.",
        "queue_count": "{n} archivo(s) en cola",
        "queue_hint": "Añade más archivos o pulsa Enter para BORRAR.",
        "session_prompt": "❱❱❱ ",
        "session_ended": "Sesión terminada.",
        "session_goodbye": "👋 Sesión terminada. Hasta pronto.",
        "continue_prompt": (
            "Presiona Enter para iniciar una nueva sesión o escribe [bold]salir[/bold] "
            "para salir..."
        ),
        "path_not_found": "✗ Ruta no encontrada:",
        "target_not_found": "✗ Objetivo no encontrado:",
        "no_files_found": "⚠ No se encontraron archivos en:",
        "type_dir": "Directorio (recursivo)",
        "type_file": "Archivo individual",
        "lbl_target": "Objetivo",
        "lbl_type": "Tipo",
        "files_to_wipe": "Archivos a borrar",
        "total_data": "Datos totales",
        "method": "Método",
        "passes": "Pases",
        "pass_values": "1) Ceros  2) Unos  3) Aleatorio",
        "dry_run_title": "🔍 SIMULACIÓN — no se modificará ningún archivo:",
        "more_files": "...y {n} archivos más",
        "warning_title": "⚠ ADVERTENCIA: ESTA ACCIÓN ES IRREVERSIBLE ⚠",
        "warning_body": (
            "Todos los archivos serán sobrescritos (de 1 a 3 pases según el estándar\n"
            "y el tipo de almacenamiento) y eliminados permanentemente.\n"
            "[bold]Los datos NO se podrán recuperar tras esta operación.[/]"
        ),
        "confirm_prompt": "  ¿Estás seguro de que deseas continuar?",
        "confirm_msg": "¿Estás seguro? [s/N]: ",
        "op_cancelled": "Operación cancelada.",
        "starting": "Iniciando...",
        "preview_title": "📋 ARCHIVOS A DESTRUIR",
        "preview_name": "Nombre",
        "preview_size": "Tamaño",
        "preview_type": "Tipo",
        "preview_total": "TOTAL",
        "dash_header": "🛡️  MADARA MASTER v{version}",
        "dash_file": "📁 Archivo",
        "dash_algorithm": "🔒 Algoritmo",
        "dash_status": "🔄 Estado",
        "dash_pass": "Pase {i}/{n} — {pattern}...",
        "pat_zeros": "Sobrescribiendo con 0x00 (Ceros)",
        "pat_ones": "Sobrescribiendo con 0xFF (Unos)",
        "pat_random": "Sobrescribiendo con Bytes Aleatorios",
        "dash_algorithm_value": "{standard} · {n} pase(s)",
        "dash_scrubbing": "🧹 Limpiando metadatos y eliminando...",
        "dash_progress": "📊 Progreso Global",
        "dash_speed": "🚀 Velocidad",
        "dash_written": "💾 Escritura Efectiva",
        "dash_file_counter": "📂 Archivo",
        "summary_title": "🧹 RESUMEN DE BORRADO",
        "metric": "Métrica",
        "value": "Valor",
        "total_targeted": "Total Archivos Objetivo",
        "files_wiped_ok": "Archivos Borrados con Éxito",
        "files_failed": "Archivos Fallidos",
        "total_overwritten": "Total Bytes Sobrescritos",
        "effective_written": "Datos Efectivos Escritos",
        "total_duration": "Duración Total",
        "avg_speed": "Velocidad Media de Escritura",
        "errors_title": "⚠ Errores",
        "more_errors": "...y {n} más",
        "all_sanitized_one": "✔ {n} ARCHIVO SOBRESCRITO Y ELIMINADO",
        "all_sanitized_many": "✔ {n} ARCHIVOS SOBRESCRITOS Y ELIMINADOS",
        "partial_wipe": "⚠ BORRADO PARCIAL — {wiped} borrados, {failed} fallidos",
        "no_files_wiped": "✗ NO SE BORRÓ NINGÚN ARCHIVO",
        "completion_msg": "ELIMINACIÓN COMPLETADA CON ÉXITO",
        "wiped": "✔ Borrado",
        "version_desc": "Sanitización segura de archivos (patrones NIST SP 800-88 / DoD 5220.22-M)",
        "version_license": "Licencia: MIT — Uso Autorizado Únicamente",
        "lbl_verify": "Verificar",
        "lbl_audit_log": "Log Auditoría",
        "wfs_title": "Borrado de Espacio Libre",
        "wfs_hint": "Creando archivo de relleno temporal para contrarrestar el wear-leveling…",
        "wfs_filling": "Rellenando espacio libre con ceros",
        "wfs_chunk": "Bloque",
        "wfs_enospc": "Disco lleno — espacio libre cubierto.",
        "wfs_syncing": "Sincronizando con el soporte físico (fsync)…",
        "wfs_removing": "Eliminando archivo de relleno…",
        "wfs_trim": "Enviando TRIM al controlador de almacenamiento…",
        "wfs_trim_ok": "TRIM enviado correctamente.",
        "wfs_trim_skip": "TRIM omitido (no es SSD/NVMe o permisos insuficientes).",
        "wfs_done": "Borrado de espacio libre completado.",
        "wfs_written": "Ceros escritos",
        "wfs_duration": "Duración",
        "wfs_error": "Error durante el borrado de espacio libre",
        "wfs_dry": "SIMULACIÓN — directorio objetivo:",
        "dangerous_target": "✗ Objetivo protegido, no se borrará:",
        "dangerous_target_hint": "Usa --allow-dangerous-target solo si estás completamente seguro.",
        "confirm_type_name": "  Escribe el nombre del directorio ({name}) para confirmar",
        "wfs_cleanup_failed": "No se pudo eliminar el archivo de relleno; bórralo a mano:",
        "dangerous_target_interactive": (
            "Los objetivos protegidos no se pueden borrar desde la sesión interactiva."
        ),
        "confirm_word": "BORRAR",
        "confirm_word_prompt": "Hay directorios en la cola. Escribe {word} para confirmar: ",
        "ssd_purge_warning": (
            "El objetivo está en un SSD/NVMe. Sobrescribir ficheros no garantiza\n"
            "NIST 800-88 Purge en flash (wear-leveling, sobreaprovisionamiento).\n"
            "Para eso, usa cifrado de disco completo o el borrado seguro de la unidad."
        ),
        "purge_forces_verify": "El estándar purge siempre verifica tras el borrado.",
        "residue_title": "Pueden quedar copias tras este borrado",
        "residue_cow_fs": (
            "Sistema de archivos copy-on-write (btrfs, ZFS, APFS, ReFS…): lo que se\n"
            "sobrescribe va a bloques nuevos y los datos antiguos pueden seguir en disco."
        ),
        "residue_network": (
            "Ubicación de red: el servidor puede guardar sus propias instantáneas,\n"
            "cachés o copias de seguridad."
        ),
        "residue_cloud_sync": (
            "Carpeta sincronizada con la nube (OneDrive, Dropbox, Google Drive, iCloud…):\n"
            "la copia de la nube y su historial de versiones no se borran. Bórralos allí."
        ),
        "residue_data_journal": (
            "ext3/ext4 montado con data=journal: el contenido puede quedar en el journal."
        ),
        "residue_hint": "Consulta la sección Limitaciones del README para más detalles.",
        "trims_sent": "TRIM enviado",
        "lbl_hash": "Hash previo",
        "yes": "Sí",
        "no": "No",
        "interrupted": "Interrumpido por el usuario.",
        "wipe_error": "Error durante el borrado:",
        "lbl_storage": "Almacenamiento",
        "lbl_free_space": "Espacio libre",
        "wfs_full_note": (
            "El disco quedará momentáneamente lleno — comportamiento esperado.\n"
            "No se modificará ningún archivo existente."
        ),
        "ctx_windows_only": "Error: solo disponible en Windows.",
        "ctx_installed": "✔ Menú contextual instalado para el usuario actual.",
        "ctx_command": "  Comando: {cmd}",
        "ctx_error": "Error: {error}",
        "banner_subtitle": "NIST SP 800-88 · DoD 5220.22-M · v{version}",
    },
}

current_lang: str = "EN"

EXIT_KEYWORDS: dict[str, frozenset[str]] = {
    "EN": frozenset(["exit", "close", "quit"]),
    "ES": frozenset(["salir", "cerrar"]),
}

CONFIRM_YES: frozenset[str] = frozenset(["y", "yes", "s", "si"])


# ─── i18n helper ─────────────────────────────────────────────────────────────


def T(key: str, **kwargs: object) -> str:
    """Look up a translation key in the active language dictionary.

    Args:
        key: Translation key defined in :data:`LANG`.
        **kwargs: Format arguments substituted into the translated string.

    Returns:
        The translated (and optionally formatted) string, or *key* itself
        if no entry is found.
    """
    text = LANG[current_lang].get(key, key)
    return text.format(**kwargs) if kwargs else text
