# 1.6.0

- Importazione mensile da file Excel .xls BPER e CSV con selezione e assegnazione delle uscite.
- Versamenti imputabili agli arretrati mantenendo la data dell’incasso.
- Riepilogo per persona in tabella e stampa individuale o complessiva.
- Rimozione del collegamento bancario e dei relativi file locali.

# 1.5.1

- Accesso HTTP locale facoltativo tramite indirizzo IPv4, sottorete autorizzata e password dedicata.
- Open Banking rimane accessibile dal pannello Home Assistant.

# 1.5.0

- Accesso facoltativo dalla LAN su HTTPS con certificato dedicato, filtro IPv4 e autenticazione separata.
- Le richieste dirette usano lo stesso registro. Il collegamento e la consultazione tramite Enable Banking restano nel pannello Home Assistant.

# 1.4.0

- L’accesso avviene dal pannello Home Assistant anche via VPN. Rimossi il listener 8100, la password dedicata e il mount dei certificati Home Assistant.
- Server con limiti di connessione, concorrenza e dimensioni delle richieste. L’esecuzione del servizio avviene con un utente senza privilegi dopo l’assegnazione dei permessi dei file esistenti.
- Le chiamate Enable Banking rispettano un limite temporale complessivo. Il registro rimane disponibile durante le richieste alla banca.

# 1.3.1

- Accetta entrambi i domini ufficiali di autorizzazione di Enable Banking per il collegamento BPER.

# 1.3.0

- Collegamento BPER in sola lettura con Enable Banking per uso personale.
- Anteprima manuale delle uscite del mese, con scelta delle spese da registrare.

# 1.2.0

- Mostra per persona gli arretrati ancora aperti, con importo e mese di origine.
- Registra gli acconti direttamente sul mese arretrato.
- Riporta gli arretrati nella stampa da browser e nell’esportazione per ScontrinoStudio 6.5.

# 1.1.0

- Accesso diretto da browser su LAN e VPN, attivabile con una password dedicata.
- Esportazione del rendiconto per ScontrinoStudio 6.4 su Mac.
