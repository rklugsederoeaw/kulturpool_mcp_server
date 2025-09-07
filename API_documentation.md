GET

[/search/](https://api.kulturpool.at/docs#/search/search_documents_search__get)

Kulturpool Suche

**Durchsucht die Kulturpool-Sammlung über die Typesense-Suchmaschine.**

Diese API leitet Suchanfragen an den Typesense-Server weiter und fügt automatisch den erforderlichen API-Schlüssel hinzu. Nutzer können ohne Authentifizierung suchen.

### Hauptparameter:

- **q**: Suchbegriff (z.B. "Wien", "Porträt", "Albertina")
- **query_by**: Felder, in denen gesucht werden soll (Standard: alle durchsuchbaren Felder)
- **filter_by**: Filter für Facetten (z.B. "dataProvider:=Albertina")
- **sort_by**: Sortierung der Ergebnisse (z.B. "titleSort:asc")

### Verfügbare Felder für query_by:

- **title**: Titel des Objekts
- **description**: Beschreibung
- **creator**: Urheber/Künstler
- **subject**: Themen/Schlagwörter
- **dataProvider**: Datenlieferant (Institution)
- **publisher**: Herausgeber
- **contributor**: Beitragende
- **coverage, spatial, temporal**: Orts- und Zeitangaben
- **dcType**: Dublin Core Typ
- **medium**: Material/Medium
- **isPartOf**: Teil einer Sammlung
- **identifier**: Identifikatoren
- **alternative**: Alternative Titel

### Verfügbare Facetten für filter_by:

- **dataProvider**: Institution (z.B. "Albertina", "Belvedere")
- **creator**: Künstler/Urheber
- **edmType**: Europeana Data Model Typ (IMAGE, VIDEO, SOUND, TEXT, 3D)
- **dcType**: Dublin Core Typ (z.B. "Fotografie", "Gemälde")
- **subject**: Themen und Schlagwörter
- **medium**: Material/Technik
- **publisher**: Herausgeber
- **isPartOf**: Sammlungszugehörigkeit
- **edmRightsName**: Rechtestatus (z.B. "Public Domain", "CC BY")
- **edmRightsReusePolicy**: Nachnutzungsrichtlinie
- **dateMin/dateMax**: Zeitraum (numerische Werte)
- **contributor**: Beitragende
- **intermediateProvider**: Zwischenanbieter

### Filterbeispiele:

- `dataProvider:=Albertina` - nur Albertina-Objekte
- `edmType:=IMAGE` - nur Bilder
- `dateMin:>1900` - nach 1900 entstanden
- `creator:*Mozart*` - Objekte mit "Mozart" im Urheber-Feld

### Sortierfelder für sort_by:

- **titleSort**: alphabetisch nach Titel
- **dataProvider**: nach Institution
- **dateMin/dateMax**: chronologisch

Die API gibt detaillierte Suchergebnisse mit Highlighting zurück.

#### Parameters

Try it out

| Name                                                                   | Description                                                                                                                                                                                                             |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| q *<br><br>string<br><br>(query)                                       | Suchbegriff                                                                                                                                                                                                             |
| query_by<br><br>string \| (string \| null)<br><br>(query)              | Kommagetrennte Liste der zu durchsuchenden Felder<br><br>*Default value* : title,description,creator,subject,dataProvider,publisher,contributor,coverage,spatial,temporal,dcType,medium,isPartOf,identifier,alternative |
| filter_by<br><br>string \| (string \| null)<br><br>(query)             | Filter für Facetten (z.B. 'dataProvider:=Albertina')                                                                                                                                                                    |
| sort_by<br><br>string \| (string \| null)<br><br>(query)               | Sortierung (z.B. 'titleSort:asc' oder 'dateMin:desc')                                                                                                                                                                   |
| page<br><br>integer<br><br>(query)                                     | Seitennummer (ab 1)<br><br>*Default value* : 1<br><br>minimum: 1                                                                                                                                                        |
| per_page<br><br>integer<br><br>(query)                                 | Anzahl Ergebnisse pro Seite (max. 250)<br><br>*Default value* : 20<br><br>maximum: 250<br><br>minimum: 1                                                                                                                |
| facet_by<br><br>string \| (string \| null)<br><br>(query)              | Kommagetrennte Liste der Facetten<br><br>*Default value* : dataProvider,creator,edmType,dcType,subject,medium,publisher,isPartOf,edmRightsName,edmRightsReusePolicy,dateMin,contributor,intermediateProvider            |
| max_facet_values<br><br>integer<br><br>(query)                         | Maximale Anzahl Facetten-Werte<br><br>*Default value* : 50<br><br>maximum: 100<br><br>minimum: 1                                                                                                                        |
| highlight_full_fields<br><br>string \| (string \| null)<br><br>(query) | Felder für vollständiges Highlighting<br><br>*Default value* : title,description,creator,subject                                                                                                                        |
| use_cache<br><br>boolean<br><br>(query)                                | Typesense-Cache verwenden<br><br>*Default value* : true<br><br>--truefalse                                                                                                                                              |

#### Responses

| Code | Description                                                                                                                                                                                                                                                                                 | Links      |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| 200  | Typesense-Suchergebnisse mit Objekten, Facetten und Highlighting<br><br>Media type<br><br>application/json<br><br>Controls `Accept` header.<br><br>- Example Value<br>- Schema<br><br>```json<br>"string"<br>```                                                                            | *No links* |
| 404  | No search results found                                                                                                                                                                                                                                                                     | *No links* |
| 422  | Validation Error<br><br>Media type<br><br>application/json<br><br>- Example Value<br>- Schema<br><br>```json<br>{<br>  "detail": [<br>    {<br>      "loc": [<br>        "string",<br>        0<br>      ],<br>      "msg": "string",<br>      "type": "string"<br>    }<br>  ]<br>}<br>``` | *No links* |
| 500  | Internal server error or Typesense API error                                                                                                                                                                                                                                                |            |
