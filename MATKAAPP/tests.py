from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch


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
        response = self.get("single_game")

        self.assertRedirects(
            response,
            f"{reverse('landing')}?next={reverse('single_game')}",
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


class EmailOtpRegistrationFlowTests(BaseGateTestCase):
    @patch("MATKAAPP.views._verify_recaptcha_response", return_value=True)
    @patch("MATKAAPP.views._is_disposable_email", return_value=False)
    @patch("MATKAAPP.views._generate_otp_6", return_value="123456")
    @patch("django.core.mail.send_mail", return_value=1)
    def test_register_then_verify_otp_creates_user(self, _send_mail, _gen_otp, _is_disposable, _verify_recaptcha):
        response = self.client.post(
            reverse("register"),
            data={
                "name": "Test User",
                "username": "testuser",
                "email": "testuser@example.com",
                "mobile": "9876543210",
                "password": "StrongPass123!@#",
                "password2": "StrongPass123!@#",
                "terms_agree": "on",
                "g-recaptcha-response": "dummy",
            },
            secure=True,
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("verify_email_otp"))

        response = self.client.post(
            reverse("verify_email_otp"),
            data={"otp": "123456"},
            secure=True,
            follow=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("otp_result"))

        self.assertTrue(User.objects.filter(username="testuser").exists())
