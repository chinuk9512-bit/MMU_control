# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


streamlit_datas = collect_data_files('streamlit')
streamlit_hiddenimports = collect_submodules('streamlit')

a = Analysis(
    ['src\\mmu_control\\web_app.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        ('src\\mmu_control\\resources\\power_supply_commands.json', 'mmu_control/resources'),
        *streamlit_datas,
    ],
    hiddenimports=[
        'mmu_control.core.automation_runner',
        'mmu_control.core.config_manager',
        'mmu_control.core.error_recovery',
        'mmu_control.core.interactive_shell',
        'mmu_control.core.minicom_manager',
        'mmu_control.core.power_supply_manager',
        'mmu_control.core.sftp_manager',
        'mmu_control.core.ssh_manager',
        'mmu_control.models.automation',
        'mmu_control.models.command_set',
        'mmu_control.models.profile',
        'mmu_control.models.settings',
        'mmu_control.storage.automation_store',
        'mmu_control.storage.command_set_store',
        *streamlit_hiddenimports,
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
    name='MMUControlWeb',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
