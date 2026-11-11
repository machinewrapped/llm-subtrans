from html import escape

from PySubtrans.Helpers.Localization import _


def GatewayInformation(description : str, homepage_url : str, models_url : str, privacy_url : str, terms_url : str) -> str:
    """Format the description and transparency links for a gateway."""
    links = (
        (_("Homepage"), homepage_url),
        (_("Available Models"), models_url),
        (_("Privacy Policy"), privacy_url),
        (_("Terms & Conditions"), terms_url),
    )
    rows = []
    for label, url in links:
        value = f'<a href="{escape(url, quote=True)}">{escape(url)}</a>' if url else _("Not available")
        rows.append(f"{escape(label)}: {value}")

    return description + "\n<p>" + "<br>".join(rows) + "</p>"
