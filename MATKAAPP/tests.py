from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class BaseGateTestCase(TestCase):
    def get(self, route_name):
        return self.client.get(reverse(route_name), secure=True)

    def mark_gate_verified(self):
        session = self.client.session
        session["captcha_verified"] = True
        session.save()


class GatekeeperSmokeTests(BaseGateTestCase):
    def test_root_route_renders_security_gate(self):
        response = self.get("landing")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "landing.html")

    def test_protected_route_redirects_until_gate_is_verified(self):
        response = self.get("user_home")

        self.assertRedirects(
            response,
            f"{reverse('landing')}?next={reverse('user_home')}",
            fetch_redirect_response=False,
        )

    def test_verified_session_can_load_public_pages(self):
        self.mark_gate_verified()

        for route_name in ("user_home", "login", "register", "display"):
            with self.subTest(route_name=route_name):
                response = self.get(route_name)
                self.assertEqual(response.status_code, 200)


class AdminHomepageRoutingTests(BaseGateTestCase):
    def test_superuser_is_redirected_to_admin_summary_from_root_after_gate(self):
        admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="pass12345",
        )
        self.client.force_login(admin_user)
        self.mark_gate_verified()

        response = self.get("landing")

        self.assertRedirects(
            response,
            reverse("admin_summary"),
            fetch_redirect_response=False,
        )
