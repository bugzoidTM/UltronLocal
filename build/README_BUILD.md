# Build & Distribuição — UltronPRO

## Estrutura

```
build/
├── launcher/
│   └── ultronpro_launcher.py   ← Ponto de entrada compilado pelo PyInstaller
├── installer/
│   └── ultronpro_setup.iss     ← Script Inno Setup (instalador profissional opcional)
├── build_exe.ps1               ← [PASSO 1] Gera o UltronPRO.exe
├── package_dist.ps1            ← [PASSO 2] Empacota tudo em .zip
└── README_BUILD.md             ← Este arquivo
```

## Como gerar o executável

### Pré-requisito (apenas na máquina de desenvolvimento)
- Python 3.9+ instalado e no PATH  
- Conexão com internet

### Passo 1 — Compilar

```powershell
cd D:\UnidadeF\UltronPro\build
.\build_exe.ps1
```

Gera: `build\dist\UltronPRO.exe`

### Passo 2 — Empacotar para distribuição

```powershell
cd D:\UnidadeF\UltronPro\build
.\package_dist.ps1
```

Gera: `build\dist\UltronPRO_Distribuivel.zip`

---

## O que acontece quando o usuário executa o .exe?

```
UltronPRO.exe
     │
     ├─► Splash screen aparece
     │
     ├─► [Verifica] PyQt5, uvicorn, fastapi, etc. instalados?
     │        └── NÃO → pip install automático (~3-10 min na 1ª vez)
     │        └── SIM → continua
     │
     ├─► Inicia servidor uvicorn em background (porta 8000)
     │
     ├─► Aguarda servidor responder
     │
     └─► Abre a janela PyQt5 (UltronWindow)
              │
              └── Ao fechar a janela → encerra o servidor automaticamente
```

## Instalador profissional (opcional)

Se quiser um instalador `.exe` com wizard (como os programas normais do Windows):

1. Baixe o Inno Setup: https://jrsoftware.org/isdl.php
2. Compile o `UltronPRO.exe` primeiro (Passo 1 acima)
3. Execute:
```powershell
iscc build\installer\ultronpro_setup.iss
```
Gera: `build\dist\installer\UltronPRO_Setup.exe`

## Notas importantes

- **Modelos de voz** (`data/models/vosk/`) e **banco de dados** (`data/ultron.db`)  
  **NÃO** estão incluídos no `.exe` — precisam ser distribuídos junto (o `package_dist.ps1` faz isso automaticamente)

- O `.exe` detecta automaticamente o diretório onde foi colocado para encontrar a pasta `backend/data/`

- Na máquina sem Python: o launcher usa o próprio Python embarcado pelo PyInstaller para fazer o `pip install`

- Tamanho estimado do pacote final: **1-2 GB** (dominado pelos modelos .gguf e banco de dados)
