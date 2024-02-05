from django.core.mail import send_mail
from django.conf import settings

def send_moderator_account_create_email(username, email, nom, prenom , password):
    subject = 'Notification de création de compte moderateur'
    
    message = f'''
    Bonjour Modérateur,

    Un compte a été créé avec les détails suivants :
    
    Nom d'utilisateur : {username}
    Email : {email}
    Nom : {nom}
    Prenom : {prenom}
    Mot de passe : {password}

    Un mot de passe temporaire a été généré pour cet utilisateur.

    Vous devez changer ce mot de passe dès sa première connexion pour des raisons de sécurité.

    Merci,
    Votre équipe d'application
    '''
    send_mail(
        subject,
        message,
        settings.EMAIL_HOST_USER,
        [email],
        fail_silently=False,
    )
