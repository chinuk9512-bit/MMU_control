# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\mmu_control\\app.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('src\\mmu_control\\resources\\power_supply_commands.json', 'mmu_control/resources'),
    ],
    hiddenimports=[
        'mmu_control.models.command_set',
        'mmu_control.core.error_recovery',
        'mmu_control.core.sftp_manager',
        'mmu_control.core.ssh_manager',
        'mmu_control.core.terminal_sequences',
        'mmu_control.models.profile',
        'mmu_control.storage.command_set_store',
        'mmu_control.storage.profile_store',
        'mmu_control.ui.command_editor_dialog',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MMUControl',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
