---
description: Controle local de dispositivos por protocolos de rede sem depender de software externo
version: 1.0.0
author: ultronpro
tags:
  - local_environment
  - devices
  - home_automation
  - tv
  - camera
  - network
allowed_tools:
  - local_environment.scan_network
  - local_environment.list_devices
  - local_environment.observe_device
  - local_environment.act_device
risk_level: medium
budget:
  max_seconds: 60
  max_calls: 12
  max_cost_usd: 0.0
when_to_use: |
  Use este skill quando o usuario pedir comandos livres sobre dispositivos locais,
  automacao residencial, TV, camera, servicos da maquina, scripts ou rede local.
  A rota deve sempre consultar o Device Registry, aplicar capability model e risk gate,
  executar observe -> act -> verify, e registrar Action Ledger.
path: local_environment_protocols
hooks:
  before: validar_device_registry_e_risco
  after: registrar_action_ledger_e_trace
success_checks:
  - comando livre convertido em device_id/action/params
  - action passa por capability model
  - risco alto exige confirmacao
  - resultado inclui verificacao ou erro operacional claro
enabled: true
---

# Local Environment Protocols Skill

Competencia operacional para controlar dispositivos cadastrados no ambiente local.

## Contrato

1. Interpretar comando em texto livre.
2. Selecionar dispositivo pelo registry e aliases.
3. Selecionar protocolo nativo quando disponivel:
   - Mock apenas para dispositivos simulados.
   - Home Assistant para entidades importadas via REST API.
   - MQTT publish direto, sem biblioteca externa, para topicos cadastrados.
   - Servicos locais e scripts registrados.
   - HTTP endpoints customizados declarados no registry.
   - Wake-on-LAN quando houver MAC cadastrado.
   - RTSP/MJPEG proxy para cameras com OpenCV/ffmpeg e validacao de stream antes de abrir player externo.
   - ONVIF WS-Discovery, mDNS, ARP cache e probe TCP para descoberta de dispositivos.
   - Webcam local via OpenCV como dispositivo `local_media`.
   - Roku ECP para Roku/TV na porta 8060.
   - Samsung Remote WebSocket para Samsung/Tizen nas portas 8001/8002 quando Home Assistant nao cobrir.
4. Executar somente capabilities registradas e permitidas.
5. Confirmar acoes de risco alto antes da execucao.
6. Registrar Action Ledger, trace e aprendizado causal.

## Exemplos

```text
Usuario: aumentar volume da TV 192.168.68.104
Rota preferida: local_environment -> media_player Home Assistant -> volume_up
Fallback: local_environment -> device net_192_168_68_104 -> volume_up -> samsung_ws
```

```text
Usuario: abrir camera 192.168.68.100
Rota: local_environment -> camera RTSP/Home Assistant/local_media -> validar stream -> view_stream -> viewer local MJPEG
Se o RTSP exigir credenciais ou caminho proprietario, registrar diagnostico e pedir stream_url/credenciais em vez de abrir URL invalida.
```

```text
Usuario: renomeie camera 192.168.68.100 para Camera da Sala
Rota: local_environment -> registry rename -> aliases persistentes
```
