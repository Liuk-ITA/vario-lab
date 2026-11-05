# Uso

All'avvio: intro di4.1s, poi inizializzazione sensore e calibrazione del riferimento.
Tenere fermo il sensore durante i primi secondi. L'acquisizione inizia dopo lo splash.

| Pulsante integrato | Azione |
|---|---|
| A breve | Prossimo filtro abilitato |
| A prolungato | Ciclo timbri abilitati |
| B breve | Ciclo volume, incluso muto |
| B prolungato | Nuovo riferimento quota |

Il numero mostra velocita verticale in m/s; barra e numero sono smussati separatamente
dal suono. La tensione in alto riguarda la batteria. La temperatura e quella misurata
dal BMP581 e puo risentire del contenitore: non e automaticamente temperatura esterna.

In XCTrack cercare la telemetria BLE **StickVario** (nome radio attuale), servizio NUS
con sentenze LK8EX1. Batteria e temperatura sono disponibili anche su servizi BLE
standard. Tastiera BLE opzionale ancora sperimentale: errore associazione/PIN aperto.

Le impostazioni si applicano tramite il configuratore separato. APPLY cambia la
sessione, SAVE salva il JSON e richiede una pausa dichiarata dell'acquisizione.
Filtri, timbri, pattern e frequenze restano scelte indipendenti. L'eventuale tastiera
e i pulsanti esterni sono disabilitati di default e non necessari al montaggio base.

Lo speaker interno ha volume limitato; udibilita in volo, autonomia e filtraggio
meccanico dell'aria richiedono ancora prove sul campo.
