const express = require("express");
const bodyParser = require("body-parser");
const nodemailer = require("nodemailer");
const crypto = require("crypto");
const jwt = require("jsonwebtoken");
require("dotenv").config();

const app = express();
app.use(bodyParser.json());

const PORT = Number(process.env.PORT || 3000);
const OTP_TTL_SECONDS = Number(process.env.OTP_TTL_SECONDS || 120);
const OTP_MAX_ATTEMPTS = Number(process.env.OTP_MAX_ATTEMPTS || 5);
const OTP_RESEND_COOLDOWN_SECONDS = Number(process.env.OTP_RESEND_COOLDOWN_SECONDS || 30);
const JWT_SECRET = process.env.JWT_SECRET;
const JWT_EXPIRES_IN = process.env.JWT_EXPIRES_IN || "1h";

// Temporary in-memory stores (replace with DB/Redis in production)
const users = {};
const otps = {};

function hashPassword(password) {
  const salt = crypto.randomBytes(16).toString("hex");
  const hash = crypto.scryptSync(password, salt, 64).toString("hex");
  return `${salt}:${hash}`;
}

function verifyPassword(password, storedHash) {
  if (!storedHash || !storedHash.includes(":")) {
    return false;
  }
  const [salt, expectedHash] = storedHash.split(":");
  const candidateHash = crypto.scryptSync(password, salt, 64).toString("hex");
  const expected = Buffer.from(expectedHash, "hex");
  const candidate = Buffer.from(candidateHash, "hex");
  if (expected.length !== candidate.length) {
    return false;
  }
  return crypto.timingSafeEqual(expected, candidate);
}

const smtpUser = process.env.YAHOO_SMTP_USER;
const smtpPass = process.env.YAHOO_SMTP_APP_PASSWORD;
if (!smtpUser || !smtpPass) {
  throw new Error("Missing SMTP credentials. Set YAHOO_SMTP_USER and YAHOO_SMTP_APP_PASSWORD.");
}
if (!JWT_SECRET) {
  throw new Error("Missing JWT secret. Set JWT_SECRET in environment.");
}

const transporter = nodemailer.createTransport({
  host: "smtp.mail.yahoo.com",
  port: 465,
  secure: true,
  auth: {
    user: smtpUser,
    pass: smtpPass,
  },
});

app.post("/signup", async (req, res) => {
  try {
    const { email, password } = req.body || {};

    if (!email || !password) {
      return res.status(400).json({ message: "Email and password are required." });
    }

    if (users[email]) {
      return res.status(400).json({ message: "User already exists." });
    }

    users[email] = { passwordHash: hashPassword(password), verified: false, createdAt: Date.now() };

    const otp = crypto.randomInt(100000, 1000000).toString();
    const expiresAt = Date.now() + OTP_TTL_SECONDS * 1000;
    otps[email] = {
      otp,
      expiresAt,
      attempts: 0,
      lastSentAt: Date.now(),
    };

    await transporter.sendMail({
      from: smtpUser,
      to: email,
      subject: "Your OTP Code",
      text: `Your verification code is: ${otp}. It expires in ${OTP_TTL_SECONDS} seconds.`,
    });

    return res.json({ message: "Signup successful. OTP sent to email.", expiresInSeconds: OTP_TTL_SECONDS });
  } catch (err) {
    console.error("Signup error:", err);
    return res.status(500).json({ message: "Error sending OTP." });
  }
});

app.post("/resend-otp", async (req, res) => {
  try {
    const { email } = req.body || {};
    if (!email) {
      return res.status(400).json({ message: "Email is required." });
    }

    const user = users[email];
    if (!user) {
      return res.status(404).json({ message: "User not found. Please signup first." });
    }
    if (user.verified) {
      return res.status(400).json({ message: "Email is already verified." });
    }

    const now = Date.now();
    const existing = otps[email];
    if (existing && now - existing.lastSentAt < OTP_RESEND_COOLDOWN_SECONDS * 1000) {
      const retryAfter = Math.ceil((OTP_RESEND_COOLDOWN_SECONDS * 1000 - (now - existing.lastSentAt)) / 1000);
      return res.status(429).json({
        message: "Please wait before requesting another OTP.",
        retryAfterSeconds: retryAfter,
      });
    }

    const otp = crypto.randomInt(100000, 1000000).toString();
    otps[email] = {
      otp,
      expiresAt: now + OTP_TTL_SECONDS * 1000,
      attempts: 0,
      lastSentAt: now,
    };

    await transporter.sendMail({
      from: smtpUser,
      to: email,
      subject: "Your OTP Code",
      text: `Your verification code is: ${otp}. It expires in ${OTP_TTL_SECONDS} seconds.`,
    });

    return res.json({ message: "New OTP sent successfully.", expiresInSeconds: OTP_TTL_SECONDS });
  } catch (err) {
    console.error("Resend OTP error:", err);
    return res.status(500).json({ message: "Error sending OTP." });
  }
});

app.post("/verify", (req, res) => {
  const { email, otp } = req.body || {};

  if (!email || !otp) {
    return res.status(400).json({ message: "Email and OTP are required." });
  }

  const otpRecord = otps[email];
  const user = users[email];

  if (!user || !otpRecord) {
    return res.status(400).json({ message: "Invalid OTP." });
  }

  if (Date.now() > otpRecord.expiresAt) {
    delete otps[email];
    return res.status(400).json({ message: "OTP expired. Please signup again." });
  }

  if (otpRecord.attempts >= OTP_MAX_ATTEMPTS) {
    delete otps[email];
    return res.status(429).json({
      message: "Maximum OTP attempts exceeded. Please request a new OTP.",
    });
  }

  if (otpRecord.otp !== otp) {
    otpRecord.attempts += 1;
    const remainingAttempts = Math.max(0, OTP_MAX_ATTEMPTS - otpRecord.attempts);
    if (remainingAttempts === 0) {
      delete otps[email];
      return res.status(429).json({
        message: "Maximum OTP attempts exceeded. Please request a new OTP.",
      });
    }
    return res.status(400).json({ message: "Invalid OTP." });
  }

  user.verified = true;
  user.verifiedAt = Date.now();
  delete otps[email];

  return res.json({ message: "Email verified successfully!" });
});

app.post("/login", (req, res) => {
  const { email, password } = req.body || {};

  if (!email || !password) {
    return res.status(400).json({ message: "Email and password are required." });
  }

  const user = users[email];
  if (!user) {
    return res.status(401).json({ message: "Invalid email or password." });
  }

  if (!verifyPassword(password, user.passwordHash)) {
    return res.status(401).json({ message: "Invalid email or password." });
  }

  if (!user.verified) {
    return res.status(403).json({ message: "Email not verified. Please verify OTP first." });
  }

  const token = jwt.sign(
    { email, verified: true },
    JWT_SECRET,
    { expiresIn: JWT_EXPIRES_IN }
  );

  return res.json({
    message: "Login successful.",
    token,
    tokenType: "Bearer",
    expiresIn: JWT_EXPIRES_IN,
  });
});

app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
