from django.http import HttpResponse


def security_txt(request):
    # Keep this short and accurate; update contact as needed.
    host = request.get_host()
    body = "\n".join(
        [
            "Contact: mailto:ChangeLifeWithNumbers@gmail.com",
            "Expires: 2027-01-01T00:00:00.000Z",
            "Preferred-Languages: en, hi",
            f"Policy: https://{host}/terms/",
            f"Acknowledgments: https://{host}/",
            f"Canonical: https://{host}/.well-known/security.txt",
        ]
    )
    return HttpResponse(body, content_type="text/plain; charset=utf-8")

