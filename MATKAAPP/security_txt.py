from django.http import HttpResponse


def security_txt(_request):
    # Keep this short and accurate; update contact as needed.
    body = "\n".join(
        [
            "Contact: mailto:ChangeLifeWithNumbers@yahoo.com",
            "Preferred-Languages: en, hi",
            "Policy: https://{host}/terms/",
            "Acknowledgments: https://{host}/",
            "Canonical: https://{host}/.well-known/security.txt",
        ]
    )
    return HttpResponse(body, content_type="text/plain; charset=utf-8")

