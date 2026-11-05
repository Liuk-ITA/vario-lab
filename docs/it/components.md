# Componenti

## Montaggio principale senza saldature

| Qta | Componente | Codice produttore | Dove cercarlo |
|---|---|---|---|
|1|M5Stack StickS3 (ESP32-S3)|K150; Mouser170-K150|[M5Stack](https://shop.m5stack.com/products/m5sticks3-esp32s3-mini-iot-dev-kit), [Mouser](https://www.mouser.it/c/?q=K150)|
|1|Adafruit BMP581, breakout STEMMA QT|6407|[Adafruit](https://www.adafruit.com/product/6407), [Mouser](https://www.mouser.it/c/?q=Adafruit%206407)|
|1|Cavo Grove a STEMMA QT/Qwiic,100mm|Adafruit4528|[Adafruit](https://www.adafruit.com/product/4528), [Mouser](https://www.mouser.it/c/?q=Adafruit%204528)|
|1|Cavo USB-C dati, adatto al computer|Nessun modello vincolante|Usare un cavo che trasporta dati, non solo ricarica|

[BOM CSV](../assets/bom.csv): usare produttore/codice/quantita nel tool di importazione
Mouser. E una distinta, non un carrello gia creato. Niente acquisti eseguiti.
Codici verificati dalle pagine prodotto; prezzi e disponibilita da controllare
al momento dell'ordine. Il codice Mouser del K150 e170-K150; per gli Adafruit
sono riportati i codici produttore, senza inventare codici distributore.

Scegliere **BMP581**, non BMP580/BMP585, e **StickS3**, non StickC Plus/Plus2.
La batteria e lo speaker sono gia nello Stick. Il cavo QT non e incluso col sensore.
Non servono amplificatore o buzzer esterni per il montaggio base.

## Variante header

Al posto del cavo Grove-QT usare quattro fili corti verso VIN/GND/SDA/SCL della
breakout, eventualmente un cavetto QT con terminali liberi; aggiungere isolamento
e fissaggio meccanico. La scelta delle terminazioni dipende dal montaggio.
Le saldature e l'attrezzatura sono necessarie solo se si salda direttamente.
I pulsanti esterni non fanno parte della distinta pubblica iniziale.
