# TP IGL Backend

## Project Overview
une application web permettant aux utilisateurs authentifiés de rechercher des articles scientifiques. Les utilisateurs peuvent filtrer les résultats, afficher les détails des articles, y compris le texte intégral en formats texte et PDF, et sauvegarder leurs articles préférés. Les administrateurs peuvent gérer les modérateurs et lancer des opérations d'upload d'articles scientifiques depuis des fichiers PDF. Après l'upload, les modérateurs peuvent vérifier et corriger les informations extraites à partir des articles PDF.

# Getting Started
## Prerequisites

* python
* pip
* elasticsearch
* mysql


## Installation
1-Clone the repository.

```bash
git clone https://github.com/khaledbenmachiche/tp_igl_backend
cd tp_igl_backend
```
2-Install dependencies.

```bash
python -m venv env
source env/bin/activate   # On Windows, use env\Scripts\activate
pip install -r requirements.txt
```

**Additionally**, you might need to configure your database settings in the `.env` file and perform migrations accordingly. The format for the `.env` file can be found in `./ScientificArticlesSearch/.env.example`.

**Create a New `.env` File:** Copy the contents of `./ScientificArticlesSearch/.env.example` and create a new file named `.env` in the same directory.


**Edit the `.env` File:** Open the newly created `.env` file and update the database-related configurations with your own settings. This may include settings such as `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, etc.

3-Start the development server.

```bash
cd ScientificArticlesSearch
python manage.py runserver
```

## Unit Tests
To ensure the robustness and correctness of the application, unit tests are included. Follow these steps to run the unit tests:
1. **Navigate to the Project Directory:**

   ```bash
   cd ScientificArticlesSearch
   ```
2. Run Unit Tests
   ```bash
   python manage.py test
   ```
   

## Docker support
  ## Prerequisites
    * Docker
    * Docker Compose
### Usage

#### run the Docker containers :

   ```bash
   docker compose up --build
   ```
#### stopping the containers :
```bash
docker compose down
```


## Contributing


1- Create a new branch for your feature or bug fix.

```bash
git checkout -b feature/my-feature
```
2- Make your changes and commit them with a clear message.

```bash
git commit -m "Add new feature"
```
3- Push your branch to the repository.

```bash
git push origin feature/my-feature
```
4- Create a pull request to the main branch of the repository.

-Remember to update the `requirements.txt` file with the necessary Django and other package versions used in your project.
    
  ```bash
  pip freeze > requirements.txt
  ```
