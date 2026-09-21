# HydroTarif

Intégration Home Assistant pour les tarifs communaux français de l'eau potable et de l'assainissement collectif, publiés par [SISPEA / Eaufrance](https://services.eaufrance.fr/pro/telechargement).

## Installation

Copier `custom_components/hydrotarif` dans le dossier `custom_components` de Home Assistant, puis redémarrer Home Assistant. Dans **Paramètres > Appareils et services > Ajouter une intégration**, chercher **HydroTarif**.

Le projet est prévu pour le dépôt GitHub `ha-hydrotarif`. Après publication, il peut être ajouté comme **dépôt personnalisé HACS de type Integration**. HACS ne peut pas installer directement un dossier local.

## Configuration

Par défaut, le formulaire utilise la position définie dans Home Assistant. Il accepte aussi des coordonnées GPS, un préfixe de code postal, une adresse complète ou un code INSEE. Avec le mode postal, saisissez 2 à 5 chiffres, validez, puis choisissez la commune dans la liste filtrée des codes postaux correspondants. Le formulaire natif Home Assistant ne rafraîchit pas cette liste pendant la frappe ; elle apparaît à l'étape suivante. Les coordonnées et les codes postaux sont résolus avec [l'API Découpage administratif](https://geo.api.gouv.fr/decoupage-administratif/communes) ; les adresses complètes sont recherchées avec le [géocodeur IGN](https://cartes.gouv.fr/aide/fr/guides-utilisateur/utiliser-les-services-de-la-geoplateforme/geocodage/). Les résultats imprécis ou ambigus sont refusés.

Chaque emplacement ajouté crée une entrée et des entités distinctes, y compris lorsque plusieurs emplacements appartiennent à la même commune. La localisation permet de sélectionner la commune SISPEA ; elle ne garantit pas un tarif spécifique à une rue ou à une zone infra-communale.

## Capteurs

- Prix de l'eau potable, en €/m³ TTC.
- Prix de l'assainissement collectif, en €/m³ TTC.
- Prix total, disponible uniquement lorsque les deux tarifs ont la même date de référence.
- Date du tarif de l'eau potable.
- Date du tarif de l'assainissement collectif.
- Dernière vérification réussie de SISPEA.
- État des données : complètes, partielles, sans assainissement collectif ou aucun tarif disponible.

Les capteurs de prix indiquent en attributs la commune, le code INSEE, l'année SISPEA et l'URL de la source. Les capteurs de suivi sont classés en diagnostic.

L'intégration vérifie SISPEA une fois par jour. Elle consulte au maximum six millésimes passés, du plus récent au plus ancien. Dans SISPEA, les données de l'année N désignent le tarif au 1er janvier N+1. Le prix au m³ est calculé sur la base d'une facture annuelle de 120 m³ et inclut donc la part fixe répartie sur ce volume. Ce n'est pas nécessairement le coût marginal d'un m³ supplémentaire.

## Limites

La fiche communale SISPEA peut être incomplète ou en retard. Un même territoire peut présenter plusieurs zones ou services tarifaires ; le tarif communal n'est alors qu'indicatif pour l'adresse précise. En absence de service d'assainissement collectif, le capteur d'assainissement et le total restent indisponibles : le coût de l'assainissement individuel n'est pas un tarif par m³. Une refonte HTML de SISPEA peut nécessiter une mise à jour de l'extracteur.

Le projet n'est pas affilié à l'OFB, à SISPEA ou à Home Assistant.

## Développement et publication

Chaque modification incrémente la version dans `custom_components/hydrotarif/manifest.json`. La CI lance les tests, Hassfest et la validation HACS à chaque push et pull request.

Pour publier, créer puis pousser un tag correspondant exactement au manifest, par exemple `v0.1.3`. Après validation des trois contrôles, le workflow crée une release GitHub avec un ZIP de `custom_components/hydrotarif`. Un tag dont la version diffère du manifest est refusé.
