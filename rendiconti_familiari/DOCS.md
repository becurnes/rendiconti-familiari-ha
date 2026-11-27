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

Importo negativo significa uscita. Una colonna **Uscite** può invece contenere importi positivi. Se Smart Web offre soltanto un PDF, usa l'inserimento manuale o copia le righe in un foglio con le tre intestazioni indicate. BPER prevede l'accesso via Open Banking tramite terze parti autorizzate; in questa versione non c'è sincronizzazione automatica.

[Documentazione Home Assistant sulle app locali](https://contributors.home-assistant.io/apps/first-app/) · [Informativa PSD2 di BPER](https://www.bper.it/footer/informative-normative/psd2-la-nuova-normativa-sui-servizi-di-pagamento)

## Accesso diretto da browser

La voce **Rendiconti** in Home Assistant continua a usare il login di Home Assistant. Per aprire lo stesso registro in una scheda indipendente:

1. In **Impostazioni → App → Rendiconti familiari → Configurazione**, imposta `password_accesso_diretto` a una password dedicata di almeno 12 caratteri.
2. Nella sezione **Rete** abilita la porta **8100/tcp** e imposta **8100** come porta host. Salva e riavvia l'app.
3. Apri `http://homeassistant.local:8100` oppure `http://IP-DEL-RASPBERRY:8100`. Fuori casa usa la VPN e l'IP locale del Raspberry.

La porta parte disattivata. Non inoltrarla sul router. HTTP è adatto solo alla rete domestica fidata o al tunnel VPN. Per usare HTTPS anche in LAN, imposta `https_accesso_diretto` e indica i file del certificato e della chiave presenti in `/ssl`, poi apri il nome host coperto dal certificato. Se il certificato non è valido, l'accesso diretto HTTPS non parte e il pannello Ingress resta disponibile.

## Stampa con ScontrinoStudio per Mac

1. Aggiorna ScontrinoStudio alla versione **6.5** e aprilo sul Mac con la stampante HOIN configurata come al solito.
2. Sul sito scegli **Stampa**, seleziona la persona o tutte le persone, indica il rotolo e premi **Scarica per ScontrinoStudio**.
3. Apri il file `.rendiconto` dal Finder o dal pulsante **Apri rendiconto…** in ScontrinoStudio. Verifica l'anteprima e premi **Stampa rendiconto**.

Il file contiene le quote, i versamenti e i saldi che hai scelto di stampare. L'apertura non stampa automaticamente e non carica il file su Notion. Dal sito puoi ancora usare **Apri stampa** per stampare direttamente dal browser.
