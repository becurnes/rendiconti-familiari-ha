# Guida a Rendiconti familiari

Il pannello compare nella barra laterale degli amministratori di Home Assistant. Se hai più amministratori e vuoi riservarlo a te, nella configurazione dell'app imposta `utente_autorizzato` al tuo nome utente di accesso (non al nome visualizzato), salva e riavvia l'app.

Home Assistant conserva i dati dell'app in `/data`. Per ritrovarli dopo un ripristino, includi **Rendiconti familiari** nei backup di Home Assistant.

## Uso del registro

- **Aggiungi spesa** seleziona in partenza Mamma e Papà. Lascia un solo nome per assegnargli l'intero importo, oppure aggiungi altre persone da **Gestisci persone**. La quota è ripartita in parti uguali. L'eventuale centesimo residuo è attribuito alla prima persona in ordine di creazione tra quelle selezionate.
- **Registra versamento** associa un acconto o un saldo a una persona e a un mese. La data del pagamento può essere successiva al mese del conto. Eventuali eccedenze sono mostrate a parte e non vengono applicate automaticamente ad altri mesi.
- Puoi navigare fra tutti i mesi o aprire **Archivio** per tornare a quelli con registrazioni. Puoi correggere data, mese, descrizione, quote e pagamenti con **Modifica**.
- In **Stampa** scegli un rendiconto individuale o quello di tutte le persone e seleziona rotolo da **58** o **80 mm**. Usa il pannello di stampa del browser sul dispositivo che vede la stampante, ad esempio Safari sul Mac con il driver della termica già configurato. Dal driver scegli la larghezza e l'altezza adatte e usa la scala al 100%. I margini effettivi e il taglio del rotolo dipendono dalla stampante e dal driver.

## Movimenti BPER

In **Importa movimenti** puoi caricare un CSV oppure incollare una tabella copiata da Excel o Numbers. In Smart Web, se trovi uno scarico Excel, aprilo sul Mac e copia le intestazioni e le colonne dei movimenti. Il sito mostra le uscite e ti lascia scegliere quali registrare. Gli altri movimenti del file non vengono archiviati. L'app segnala i movimenti già registrati quando ritrova la stessa data, descrizione e cifra. Per importi e descrizioni identici nello stesso giorno, mantiene distinte le occorrenze presenti nel medesimo elenco.

Esempio di CSV di prova:

```csv
Data;Descrizione;Importo
05/11/2026;Bolletta gas;-84,51
06/11/2026;Bonifico ricevuto;30,00
```

Importo negativo significa uscita. Una colonna **Uscite** può invece contenere importi positivi. Se Smart Web offre soltanto un PDF, usa l'inserimento manuale o copia le righe in un foglio con le tre intestazioni indicate. BPER prevede l'accesso via Open Banking tramite terze parti autorizzate; in questa versione non c'è sincronizzazione automatica.

[Documentazione Home Assistant sulle app locali](https://contributors.home-assistant.io/apps/first-app/) · [Informativa PSD2 di BPER](https://www.bper.it/footer/informative-normative/psd2-la-nuova-normativa-sui-servizi-di-pagamento)
