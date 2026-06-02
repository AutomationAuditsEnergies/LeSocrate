# Porter un template Claude Design vers les slides React

Ce memo documente la methode qui a permis de reproduire fidelement la slide `Programme de la journee` du fichier Claude Design `Sales Hacking - Formation.html` dans les templates React du projet.

## Objectif

Quand un template HTML/CSS vient de Claude Design, il ne faut pas le reinterpreter en responsive classique. Il faut d'abord porter sa scene source telle quelle, puis l'adapter a l'application par un wrapper de scale.

Le but est de conserver :

- les polices exactes ;
- le fond exact ;
- les espacements exacts ;
- le chrome exact de la slide source ;
- les tailles internes du canvas Claude ;
- le routage correct dans les previews et les slides generees.

## Ce qui avait bloque

Le fichier Claude rend ses slides dans un canvas fixe `1920x1080`. Notre premiere version React utilisait une slide responsive avec `vw`, `cqw` et le composant chrome commun `DeckSlide`.

Resultat :

- les polices etaient calculees trop petites ;
- la grille de fond ne tombait pas aux memes endroits ;
- les gradients etaient recalcules sur une autre taille ;
- le logo n'avait pas exactement la meme casse ;
- le vieux chrome affichait encore `EN DIRECT`, `TP-CRCD` et `TYPE`.

La correction a ete de faire une vraie scene interne fixe `1920x1080`, puis de la scaler dans un shell React.

## Workflow a suivre

1. Recuperer le HTML Claude complet.

   Si le fichier est bundle/minifie, l'extraire dans un fichier temporaire lisible, par exemple `/private/tmp/sales-hacking-unpacked.html`.

2. Identifier la section source exacte.

   Chercher le `section` de la slide, son `class`, son markup et les blocs CSS associes.

   Exemple :

   ```html
   <section class="slide s-program" data-screen-label="02 Programme journée">
     <div class="chrome">
       <div class="brand"><span class="mark">Sales</span><span class="tag">hacking</span></div>
     </div>
     ...
   </section>
   ```

3. Copier les tokens visuels avant de coder.

   Relever les variables, les fonts, les couleurs, les gradients, la grille, le grain, les tailles et les positions.

   Points critiques :

   - `--f-display`
   - `--f-head`
   - `--f-body`
   - `--f-mono`
   - `--f-script`
   - `--coral`
   - `--ink`
   - gradients de fond
   - `background-size` de la grille
   - `width: 1920px`
   - `height: 1080px`

4. Ne pas utiliser le template commun si le chrome source est different.

   Si la slide Claude n'a pas `EN DIRECT`, `pages` ou `TYPE`, ne pas envelopper avec `DeckSlide`. Creer un wrapper dedie.

5. Creer un shell + une stage fixe.

   Structure recommandee :

   ```jsx
   <div className="deck-program7-shell" ref={shellRef}>
     <section className="deck-program7-stage" style={{ transform: `scale(${scale})` }}>
       ...
     </section>
   </div>
   ```

   CSS recommande :

   ```css
   .deck-program7-shell {
     width: 100%;
     max-width: 1200px;
     aspect-ratio: 16 / 9;
     position: relative;
     overflow: hidden;
   }

   .deck-program7-stage {
     position: absolute;
     inset: 0 auto auto 0;
     width: 1920px;
     height: 1080px;
     transform-origin: top left;
   }
   ```

6. Calculer le scale avec `ResizeObserver`.

   Exemple :

   ```jsx
   const useSlideStageScale = () => {
     const ref = useRef(null);
     const [scale, setScale] = useState(0.625);

     useLayoutEffect(() => {
       if (!ref.current) return undefined;
       const update = () => {
         const width = ref.current?.clientWidth || 1200;
         setScale(width / 1920);
       };
       update();
       const observer = new ResizeObserver(update);
       observer.observe(ref.current);
       return () => observer.disconnect();
     }, []);

     return [ref, scale];
   };
   ```

7. Reproduire les dimensions source en pixels, pas en unites fluides.

   Si Claude a :

   ```css
   font-size: 104px;
   gap: 120px;
   padding: 0 140px;
   background-size: 64px 64px;
   ```

   Le template React doit garder les memes valeurs dans la stage `1920x1080`.

8. Rattacher les variables CSS au wrapper dedie.

   Si le nouveau template n'est plus enfant de `.deck-slide`, il ne herite plus de ses variables. Il faut donc poser les tokens sur le shell ou sur la stage.

   Exemple :

   ```css
   .deck-program7-shell {
     --coral: #ff5d6c;
     --ink: #fff;
     --f-display: 'Archivo Black', 'Archivo', sans-serif;
     --f-head: 'Archivo', sans-serif;
     --f-body: 'Manrope', sans-serif;
     --f-mono: 'JetBrains Mono', ui-monospace, monospace;
     --f-script: 'Caveat', cursive;
   }
   ```

9. Normaliser les donnees qui changent le rendu.

   Exemple : le logo source etait `Sales` + `hacking`, pas `SALES` + `HACKING`. Meme avec la bonne police, la casse change le dessin des lettres.

10. Router le template exact.

   Si un ancien template `day_program` existe deja, eviter de le remplacer aveuglement. Router le cas exact vers le nouveau template, par exemple quand il y a 7 items :

   ```jsx
   const isSevenStepDayProgram = Array.isArray(slide.data?.items) && slide.data.items.length === 7;

   case 'day_program':
     return isSevenStepDayProgram
       ? <DeckDayProgram7Steps {...slide.data} {...commonProps} />
       : <DeckAgenda {...slide.data} {...commonProps} />;
   ```

11. Ajouter une entree de test visible.

   Dans `frontend/src/pages/TestSlides.jsx`, ajouter le template dans `Deck fourni` avec un label clair :

   ```text
   02 Programme journée · exact
   ```

## Verification obligatoire

Toujours verifier dans le navigateur, pas seulement par lecture du CSS.

Checklist :

- attendre `document.fonts.ready` ;
- capturer la slide React ;
- comparer avec une capture de la slide Claude ;
- verifier les tailles calculees ;
- verifier les familles de polices calculees ;
- verifier que le chrome parasite n'existe pas dans le DOM.

Exemple de mesures utiles :

```js
{
  stageWidth: "1920px",
  stageHeight: "1080px",
  h1FontSize: "104px",
  itemFontSize: "35px",
  brandMarkText: "Sales",
  brandTagText: "hacking",
  hasEnDirect: false,
  hasTpCrcd: false,
  hasType: false,
  fontsReady: "loaded"
}
```

## Commandes utiles

Build :

```bash
cd frontend
npm run build
```

Preview locale :

```text
http://127.0.0.1:5174/test-slides
```

Slide de reference actuelle :

```text
Deck fourni -> 02 Programme journée · exact
```

## Regle pratique

Pour chaque nouveau template Claude, partir du principe suivant :

> Claude Design donne un canvas fixe. React doit porter ce canvas, pas le redesign.

Ensuite seulement, connecter les donnees dynamiques du projet.

## Fichiers touches lors de l'exemple reussi

- `frontend/src/components/slides/templates/DeckTemplates.jsx`
- `frontend/src/components/slides/templates/DeckTemplates.css`
- `frontend/src/pages/GeneratedSlides.jsx`
- `frontend/src/pages/FormationPipeline.jsx`
- `frontend/src/pages/TestSlides.jsx`

Commit de reference :

```text
9d0a952 Match day program slide to source deck
```
