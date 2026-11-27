# Guida a Rendiconti familiari

Il pannello compare nella barra laterale degli amministratori di Home Assistant. Se hai più amministratori e vuoi riservarlo a te, nella configurazione dell'app imposta `utente_autorizzato` al tuo nome utente di accesso (non al nome visualizzato), salva e riavvia l'app.

Home Assistant conserva i dati dell'app in `/data`. Per ritrovarli dopo un ripristino, includi **Rendiconti familiari** nei backup di Home Assistant.

## Uso del registro

- **Aggiungi spesa** seleziona in partenza Mamma e Papà. Lascia un solo nome per assegnargli l'intero importo, oppure aggiungi altre persone da **Gestisci persone**. La quota è ripartita in parti uguali. L'eventuale centesimo residuo è attribuito alla prima persona in ordine di creazione tra quelle selezionate.
- **Registra versamento** associa un acconto o un saldo a una persona e a un mese. La data del pagamento può essere successiva al mese del conto. Eventuali eccedenze sono mostrate a parte e non vengono applicate automaticamente ad altri mesi.
- Puoi navigare fra tutti i mesi o aprire **Archivio** per tornare a quelli con registrazioni. Puoi correggere data, mese, descrizione, quote e pagamenti con **Modifica**.
- In **Stampa** scegli un rendiconto individuale o quello di tutte le persone e seleziona rotolo da **58** o **80 mm**. Usa il pannello di stampa del browser sul dispositivo che vede la stampante, ad esempio Safari sul Mac con il driver della termica già configurato. Dal driver scegli la larghezza e l'altezza adatte e usa la scala al 100%. I margini effettivi e il taglio del rotolo dipendono dalla stampante e dal driver.

## Arretrati

In ogni rendiconto vedi separatamente il residuo del mese e gli importi ancora da ricevere per i mesi precedenti. Gli arretrati mostrano il saldo aggiornato ai versamenti già registrati. Le spese e gli acconti rimangono nel loro mese di origine, anche se il pagamento avviene dopo. Un'eventuale eccedenza di un mese non compensa gli arretrati.

Da **Arretrati dei mesi precedenti**, usa **Registra acconto** per registrare un versamento sul mese indicato oppure **Apri mese** per vedere tutte le sue spese. Puoi modificare l'importo prima di salvare. Gli arretrati sono disponibili anche nella stampa da browser e in ScontrinoStudio 6.5.

## Movimenti BPER

In **Importa movimenti** puoi caricare un CSV oppure incollare una tabella copiata da Excel o Numbers. In Smart Web, se trovi uno scarico Excel, aprilo sul Mac e copia le intestazioni e le colonne dei movimenti. Il sito mostra le uscite e ti lascia scegliere quali registrare. Gli altri movimenti del file non vengono archiviati. L'app segnala i movimenti già registrati quando ritrova la stessa data, descrizione e cifra. Per importi e descrizioni identici nello stesso giorno, mantiene distinte le occorrenze presenti nel medesimo elenco.

Esempio di CSV di prova:

```csv
Data;Descrizione;Importo
05/11/2026;Bolletta gas;-84,51
06/11/2026;Bonifico ricevuto;30,00
```

Importo negativo significa uscita. Una colonna **Uscite** può invece contenere importi positivi. Se Smart Web offre soltanto un PDF, usa l'inserimento manuale o copia le righe in un foglio con le tre intestazioni indicate. Per leggere i movimenti dal conto senza un file puoi attivare il collegamento Open Banking descritto qui sotto.

[Documentazione Home Assistant sulle app locali](https://contributors.home-assistant.io/apps/first-app/) · [Informativa PSD2 di BPER](https://www.bper.it/footer/informative-normative/psd2-la-nuova-normativa-sui-servizi-di-pagamento)

## Accesso locale e via VPN

Dalla versione 1.4.0 apri **Rendiconti** dal pannello di Home Assistant. Fuori casa connettiti prima alla VPN e apri Home Assistant al suo indirizzo abituale. Usa un indirizzo HTTPS con certificato valido se configurato. Quando la VPN termina sul router, HTTPS protegge anche il tratto tra router e Raspberry.

Prima dell’aggiornamento, verifica di poter aprire Home Assistant via VPN e crea un backup cifrato che includa l’app. Mantieni la modalità di protezione attiva. L’aggiornamento conserva database, configurazione bancaria e filtro utente. La vecchia porta diretta 8100 e la relativa password non sono più disponibili. Rimuovi dal router e da eventuali proxy le vecchie regole che pubblicavano l’add-on. Dopo l’aggiornamento verifica l’apertura dal pannello in LAN e via VPN.

## Stampa con ScontrinoStudio per Mac

1. Aggiorna ScontrinoStudio alla versione **6.5** e aprilo sul Mac con la stampante HOIN configurata come al solito.
2. Sul sito scegli **Stampa**, seleziona la persona o tutte le persone, indica il rotolo e premi **Scarica per ScontrinoStudio**.
3. Apri il file `.rendiconto` dal Finder o dal pulsante **Apri rendiconto…** in ScontrinoStudio. Verifica l'anteprima e premi **Stampa rendiconto**.

Il file contiene le quote, i versamenti e i saldi che hai scelto di stampare. L'apertura non stampa automaticamente e non carica il file su Notion. Dal sito puoi ancora usare **Apri stampa** per stampare direttamente dal browser.

## BPER tramite Enable Banking

La funzione consulta, su richiesta, le uscite in euro già contabilizzate del mese che stai visualizzando. Per avviarla, apri il rendiconto dal pannello Home Assistant. Per un accesso remoto usa la VPN e, quando configurato, l’indirizzo HTTPS di Home Assistant.

### Prima configurazione

1. In **Importa movimenti → Open Banking**, premi **Genera e scarica certificato pubblico**. La chiave privata viene creata e conservata sul Raspberry in `/data`. Il file che scarichi è il certificato pubblico.
2. Accedi al [pannello di Enable Banking](https://enablebanking.com/sign-in/) e registra una nuova applicazione **Production**. Scegli il caricamento di un certificato e usa il file appena scaricato. Nel campo **Allowed Redirect URL** inserisci l’indirizzo HTTPS che vedi in Rendiconti, di default `https://localhost:28787/rendiconti-bper`. Se il pannello accetta l’alternativa `https://127.0.0.1:28787/rendiconti-bper`, seleziona lo stesso indirizzo anche in Rendiconti.
3. In Enable Banking attiva la modalità riservata ai propri conti (**Activate by linking accounts**) e collega il tuo conto personale scegliendo **BPER Banca**. Il pannello potrebbe chiedere dettagli sull’app durante la registrazione. Le condizioni e l’informativa del fornitore si consultano prima di dare il consenso.
4. Copia l’**Application ID** da Enable Banking, incollalo in Rendiconti e salva. Premi **Collega BPER**, poi **Continua su Enable Banking e BPER**. Autorizza la consultazione dei movimenti sulla pagina di BPER.
5. Dopo il consenso il browser apre l’indirizzo di rientro locale. È normale che non ci sia un sito in ascolto a quell’indirizzo. Copia tutto l’URL dalla barra del browser e incollalo **solo** nel campo di rientro dentro Rendiconti, mentre l’autorizzazione è in corso. Premi **Completa collegamento**.
6. Premi **Aggiorna movimenti** e usa **Usa** accanto a una spesa familiare. Controlla importo e quote, poi salva. I movimenti visualizzati in anteprima restano temporanei. Il sito segnala i movimenti già importati e i possibili doppioni per data e importo.

L’app chiede un consenso fino a 30 giorni, compatibilmente con i limiti indicati dal fornitore per BPER. Alla scadenza o se il consenso viene revocato, scollega e ripeti l’autorizzazione. **Scollega conto** richiede a Enable Banking di chiudere la sessione. Se vuoi accertarti che il consenso sia revocato anche lato banca, verificalo direttamente con BPER. I dati salvati nei rendiconti rimangono nel registro. Tieni privati i backup dell’app, che possono contenere la chiave e la sessione bancaria.

[Documentazione di Enable Banking per l’uso personale](https://enablebanking.com/docs/api/linked-accounts/) · [Supporto BPER](https://enablebanking.com/docs/markets/it/#bper-banca)
