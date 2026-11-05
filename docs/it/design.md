# Architettura e scelte

L'obiettivo e un variometro riproducibile senza elettronica aggiuntiva per audio,
display o batteria. StickS3 integra queste funzioni; la breakout Adafruit evita
di dover assemblare il sensore Bosch nudo.

Il BMP581 lavora NORMAL80Hz, OSRpressione16x/temperatura4x, IIRoff, I2C400kHz,
FIFOpressione+temperatura/watermark4. La FIFO assorbe ritardi brevi del programma;
la sua capacita e limitata e non rende tollerabili pause arbitrarie. I campioni
hanno tempi nominali ricostruiti: non sono timestamp hardware per ogni frame.

`src/bmp581.py` e `sensor_bus.py` isolano acquisizione e scelta cablaggio.
`filters.py` gestisce le stime; `pcm_audio.py` usa tabelle originali e coda audio
nativa, preservando la fase per il suono continuo. `display.py` riusa un canvas.
`configuration.py` gestisce impostazioni, `ble_link.py` la telemetria.

Splash scelto: suono precalcolato suPC dallo stesso generatore PCM classico,
con velocita sintetica1->1.5->1m/s; movimento verticale segue intenzionalmente
il tono, non la quota fisica integrata. Vento e due campanelline sono sintetizzati
originali. Nessun campione Apple o registrazione commerciale e incluso.

Le diverse stime sono confrontabili, non ricostruzioni garantite di prodotti
commerciali. Nome SkyBean indica un adattamento del principio di filtraggio;
non implica identita con il dispositivo originale. Fusione IMU non implementata.
