# Guida a Rendiconti familiari

Il pannello compare nella barra laterale degli amministratori di Home Assistant. Se hai più amministratori e vuoi riservarlo a te, nella configurazione dell'app imposta `utente_autorizzato` al tuo nome utente di accesso (non al nome visualizzato), salva e riavvia l'app.

Home Assistant conserva i dati dell'app in `/data`. Per ritrovarli dopo un ripristino, includi **Rendiconti familiari** nei backup di Home Assistant.

## Uso del registro

- **Aggiungi spesa** seleziona in partenza Mamma e Papà. Lascia un solo nome per assegnargli l'intero importo, oppure aggiungi altre persone da **Gestisci persone**. La quota è ripartita in parti uguali. L'eventuale centesimo residuo è attribuito alla prima persona in ordine di creazione tra quelle selezionate.
- **Registra versamento** associa un acconto o un saldo a una persona e a un mese. La data del pagamento può essere successiva al mese del conto. Eventuali eccedenze sono mostrate a parte e non vengono applicate automaticamente ad altri mesi.
- Puoi navigare fra tutti i mesi o aprire **Archivio** per tornare a quelli con registrazioni. Puoi correggere data, mese, descrizione, quote e pagamenti con **Modifica**.
- In **Stampa** scegli un rendiconto individuale o quello di tutte le persone e seleziona rotolo da **58** o **80 mm**. Usa il pannello di stampa del browser sul dispositivo che vede la stampante, ad esempio Safari sul Mac con il driver della termica già configurato. Dal driver scegli la larghezza e l'altezza adatte e usa la scala al 100%. I margini effettivi e il taglio del rotolo dipendono dalla stampante e dal driver.

## Arretrati

Il rendiconto mostra il residuo del mese e gli importi ancora da ricevere per i mesi precedenti. Quando registri un versamento per una persona con arretrati, scegli se imputarlo al mese corrente, a un singolo mese precedente oppure agli arretrati dal più vecchio. L’eventuale eccedenza sul residuo degli arretrati selezionati resta sul mese del versamento. Il registro conserva la data effettiva dell’incasso e mostra i mesi a cui il pagamento è stato imputato.

Da **Arretrati dei mesi precedenti**, usa **Registra versamento** per proporre il saldo del mese indicato oppure **Apri mese** per vedere spese e versamenti imputati a quel mese. La stampa e il file per ScontrinoStudio riportano separatamente il residuo del mese e gli arretrati.

## Importazione dei movimenti

1. In **Importa movimenti**, carica il file Excel **.xls** esportato da BPER Smart Web o un CSV. Puoi anche incollare una tabella con intestazioni.
2. Seleziona il mese d’importazione. Il file BPER viene letto per **Data operazione** e mostra solo le uscite contabilizzate. I movimenti già importati sono indicati nell’anteprima. Controlla le righe segnalate come possibili doppioni per data e importo.
3. Spunta le spese da registrare e scegli a chi addebitarle. Mamma e Papà dividono la spesa in parti uguali. Scegli un singolo nome per addebitargli l’intera spesa oppure **Più persone** per dividerla tra gli intestatari scelti. Usa **Gestisci persone** per aggiungere o rinominare un intestatario direttamente dall’importazione.
4. Premi **Salva selezione**. Soltanto le uscite selezionate vengono salvate nel registro. Gli intestatari sono disponibili anche nella stampa individuale o complessiva.

Esempio di CSV di prova:

```csv
Data;Descrizione;Importo
05/11/2026;Bolletta gas;-84,51
06/11/2026;Bonifico ricevuto;30,00
```

Importo negativo significa uscita. Una colonna **Uscite** può invece contenere importi positivi. Se Smart Web offre soltanto un PDF, usa l'inserimento manuale o copia le righe in un foglio con le tre intestazioni indicate.

[Documentazione Home Assistant sulle app locali](https://contributors.home-assistant.io/apps/first-app/)

## Accesso locale e via VPN

Puoi aprire **Rendiconti** dal pannello di Home Assistant. Fuori casa connettiti prima alla VPN e apri Home Assistant al suo indirizzo abituale. Usa un indirizzo HTTPS con certificato valido se configurato. Quando la VPN termina sul router, HTTPS protegge anche il tratto tra router e Raspberry.

Prima dell’aggiornamento, verifica di poter aprire Home Assistant via VPN e crea un backup cifrato che includa l’app. Mantieni la modalità di protezione attiva. L’aggiornamento conserva il database e il filtro utente. Rimuovi dal router e da eventuali proxy le vecchie regole che pubblicavano l’add-on. Dopo l’aggiornamento verifica l’apertura dal pannello in LAN e via VPN.

## Accesso diretto HTTPS in LAN

L’accesso diretto è facoltativo. Usa un nome DNS dedicato che in LAN risolve all’IPv4 del Raspberry. Puoi usare un sottodominio di tua proprietà e ottenere il certificato tramite convalida DNS-01, che funziona senza inoltrare porte. Usa un certificato con catena riconosciuta dai dispositivi. Se usi una CA locale, distribuisci il suo certificato di fiducia su ciascun dispositivo prima di provare l’accesso.

1. In **app_configs** trova la cartella dedicata a Rendiconti familiari. Puoi raggiungerla da una condivisione o da un editor già autorizzato. Copia **lan-fullchain.pem** e **lan-privkey.pem**. Usa una chiave dedicata a questo servizio e limita l’accesso al file. La cartella è inclusa nei backup dell’app. Usa backup cifrati.
2. Sul Mac, in una cartella privata, crea **lan-users.htpasswd** con `umask 077` e `htpasswd -c -B -C 10 lan-users.htpasswd tommaso`. Inserisci al prompt una password casuale dedicata, ad esempio di 24 caratteri. Copia solo il file con l’hash nella cartella dell’app. Per aggiungere persone, ripeti senza `-c`, che riscriverebbe il file.
3. Nella configurazione attiva `lan_https`. In `lan_hostname` inserisci il nome esatto del certificato. In `lan_ipv4` inserisci la tua rete effettiva, ad esempio `192.168.178.0/24`. Nella sezione **Rete** mappa la porta host **8443** e riavvia. Il listener accetta soltanto HTTPS. Un certificato mancante, scaduto o non corrispondente, una chiave incompatibile o una configurazione incompleta lasciano disponibile il pannello Home Assistant.
4. Dalla LAN apri `https://nome-scelto:8443`. Verifica che Safari riconosca il certificato prima di inserire la password. Lascia chiusi l’inoltro della porta sul router e sul proxy, e limita l’accesso alla LAN prevista nel firewall. Sui dispositivi condivisi usa una finestra privata e chiudila a fine lavoro, perché il browser può conservare le credenziali HTTP Basic per la sessione.
5. Al rinnovo sostituisci certificato e chiave, poi riavvia l’app. Verifica il nuovo certificato dal browser. Per disattivare l’accesso, spegni `lan_https`, svuota il mapping di rete e riavvia.

Spese, versamenti, importazione ed esportazione usano lo stesso registro del pannello. [Convalida DNS-01](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge)

## Stampa con ScontrinoStudio per Mac

1. Aggiorna ScontrinoStudio alla versione **6.5** e aprilo sul Mac con la stampante HOIN configurata come al solito.
2. Sul sito scegli **Stampa**, seleziona la persona o tutte le persone, indica il rotolo e premi **Scarica per ScontrinoStudio**.
3. Apri il file `.rendiconto` dal Finder o dal pulsante **Apri rendiconto…** in ScontrinoStudio. Verifica l'anteprima e premi **Stampa rendiconto**.

Il file contiene le quote, i versamenti e i saldi che hai scelto di stampare. L'apertura non stampa automaticamente e non carica il file su Notion. Dal sito puoi ancora usare **Apri stampa** per stampare direttamente dal browser.

## Rimozione del collegamento bancario

Dalla versione 1.6.0, Rendiconti importa i movimenti dai file. Al primo avvio vengono rimossi i file locali di configurazione, sessione e certificato della vecchia integrazione. Le spese già salvate restano nel database. Se avevi autorizzato l’accesso al conto, revoca anche il consenso presso BPER o Enable Banking. I backup delle versioni precedenti possono contenere le credenziali della vecchia integrazione.
