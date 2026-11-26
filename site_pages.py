"""Default public site pages and a safe renderer for owner-editable text."""

from __future__ import annotations

import html
import re

CONTACT_KEY = "contact"
TERMS_KEY = "terms"
PRIVACY_KEY = "privacy"

DEFAULT_CONTACT = """# Contact Us

Last updated: 26 November 2026

The Discord All In One Bot (also called Meowchi Cafe) and this website are operated by an individual known as Whiskey/WarRaven.

Please do not send passwords, payment card details, or Discord tokens in a message. If your question is about a paid subscription, say so and include the server name or server ID if you can.
"""

DEFAULT_TERMS = """# Terms & Conditions

Last updated: 26 November 2026

These terms explain how you may use Discord All In One Bot (also called Fun bot) and its website dashboard at discordallinonebot.online (together, the "Service"). The Service is operated by an individual sole operator in Victoria, Australia, known as Whiskey/WarRaven (the "Operator"). The Operator is not a company and does not have an Australian Business Number (ABN).

These terms have not been reviewed by a lawyer. They are written in plain English to describe the Service and to set out a reasonable allocation of risk. They are not legal advice.

By inviting the bot to a Discord server, using its commands, signing in to the dashboard, or paying for Premium, you agree to these terms. If you do not agree, do not use the Service.

# 1. Acceptance

You accept these terms when you first use the Service, and each time you continue to use it. If you use the Service on behalf of a Discord server, you confirm that you have authority to accept these terms for that use (for example, as an administrator or with the server owner's permission).

# 2. Eligibility

You must meet Discord's minimum age requirement and you must follow Discord's Terms of Service and Community Guidelines. The Service is for people who are allowed to use Discord. If you add the bot to a server, you confirm that you have the right to do so.

# 3. Licence to use the Service

The Operator grants you a limited, personal, non-exclusive, non-transferable, revocable licence to use the Service for your Discord servers, in line with these terms. You do not own the bot, the dashboard, the name, the branding, the source materials, or any related software. Nothing in these terms transfers intellectual property or any other ownership right to you.

# 4. Acceptable use and prohibited conduct

You must use the Service lawfully and fairly. You must not:

- Use the Service to break the law, Discord's rules, or these terms
- Try to hack, disrupt, overload, reverse engineer, or bypass the Service or its security
- Use the bot to harass, abuse, scam, defame, or unlawfully collect information about other people
- Impersonate the Operator or misrepresent your relationship with the Service
- Resell, sublicense, or commercially exploit access to the Service except as the Operator expressly agrees in writing
- Interfere with other servers' or users' use of the Service
- Attempt to extract or misuse data that you are not authorised to access

The Operator may suspend or end access if this section is breached, or if the Operator reasonably believes it has been breached.

# 5. Server admins are responsible for how they use the tools

If you manage a server that uses the bot, you are responsible for how the bot is configured and used in that server. This includes moderation commands and dashboard actions (including ban, unban, kick, mute and warn), alt detection, level roles, XP adjustments, and custom welcome, leave and ban messages.

The Operator does not review or control the content of your custom messages, the reasons you give for punishments, or the decisions you make about members. You must make sure those actions and messages are lawful, accurate, and appropriate for your community. You are responsible for disputes with your members that arise from your use of these tools.

# 6. Data and privacy

The Service stores information needed to operate the features a server uses. This may include Discord user and server IDs, usernames or display names when they appear in logs, XP and levels, voice-time totals, moderation logs and warnings, alt-detection signals and related settings, welcome, leave and ban message text, channel and role assignments, dashboard session data, and Premium or billing records.

This information is used to provide the Service, to protect it, and to manage subscriptions. A fuller description is in the Privacy Policy at /privacy.

You may ask for stored data about your account or server to be deleted by contacting the Operator through the Contact Us page. Some records may be kept where the Operator is required or reasonably needs them (for example, billing or security records).

Discord and Stripe are separate third-party services, each with their own terms and privacy policies. The Operator does not control those services.

# 7. Subscriptions, auto-renewal, cancellation and price changes

Paid Premium is billed per Discord server. Current prices are US$10 per month or US$100 per year, paid through Stripe. Prices are in United States dollars unless stated otherwise.

Subscriptions renew automatically at the end of each billing period unless you cancel before renewal. You can cancel or manage payment methods through the Stripe customer portal linked from the dashboard billing page. Cancellation stops future charges. It does not usually refund time already paid for in the current period.

The Operator may also grant Premium manually, including for a limited time or indefinitely, without a Stripe payment. Manual grants can be changed or revoked by the Operator.

The Operator may change prices or plans. If a change affects an existing paid subscription, the Operator will give reasonable notice (for example, through the dashboard, a message from the bot, or the contact method published on the Contact Us page). Unless the law requires otherwise, the change will apply from the next renewal.

# 8. Refunds

Premium fees are generally non-refundable once paid, including for unused time in a billing period, unused features, or if you remove the bot from a server.

This does not exclude, restrict or modify any rights you have under the Australian Consumer Law (ACL) or any other law that cannot be excluded. If the ACL requires a refund or another remedy, you are entitled to that remedy.

# 9. Availability and changes to the Service

The Service is provided "as is" and "as available". The Operator does not guarantee uptime, response times, or that any feature will be error-free, uninterrupted, or unchanged. Hosting, Discord, Stripe or other third parties may fail, limit access, or change their services.

The Operator may add, change, or remove features, and may take the Service offline for maintenance or other reasons, without liability to you where the law allows.

# 10. Suspension and termination

The Operator may suspend or end your access to the bot or dashboard, or remove the bot from a server, at the Operator's discretion. That may happen, for example, if you breach these terms, if a payment fails, if continuing would expose the Operator or others to risk, or if the Operator decides to stop offering the Service.

You may stop using the Service at any time by removing the bot from your servers and cancelling any paid subscription.

After termination, stored server data may be deleted, subject to the Privacy Policy and any records the Operator must or reasonably should keep.

# 11. Disclaimer of warranties

To the maximum extent permitted by law, the Operator does not give warranties or guarantees about the Service, including implied warranties of merchantability, fitness for a particular purpose, quiet enjoyment, or non-infringement.

Nothing in these terms excludes, restricts or modifies any consumer guarantee, right or remedy under the Australian Consumer Law that cannot be excluded.

Where the Operator is allowed to limit liability for a failure to comply with a consumer guarantee, the Operator's liability is limited (at the Operator's option, where the law permits) to supplying the Service again or paying the cost of having it supplied again.

# 12. Limitation of liability

To the maximum extent permitted by law, and subject to the Australian Consumer Law, the Operator is not liable for indirect, incidental, special, consequential or punitive loss, or for lost profits, lost data, lost goodwill, or business interruption, even if the Operator was told that loss was possible.

Subject to the ACL, the Operator's total liability to you for all claims arising out of or in connection with the Service or these terms is limited to the amount of Premium fees you paid to the Operator for the affected server in the 3 months before the claim.

This section does not limit liability that cannot be limited by law, including liability for fraud, or for death or personal injury caused by negligence where that cannot be excluded.

# 13. Indemnity

You agree to indemnify and hold the Operator harmless from claims, losses, damages, and reasonable legal costs arising out of your use of the Service, your server's configuration or moderation actions, your custom messages, your content, or your breach of these terms or of the law, except to the extent a court finds the Operator caused the loss by the Operator's own fraud or, where it cannot be excluded, negligence.

# 14. Third-party services

The Service depends on third parties, including Discord, Stripe, and Railway (hosting). Your use of those services is also governed by their terms and policies. The Operator is not responsible for outages, policy changes, data handling, or decisions by those third parties.

# 15. Intellectual property

The bot, dashboard, design, documentation, and related materials are owned by the Operator or its licensors. You may not copy, modify, distribute, or create derivative works from them except as allowed by these terms or by law (for example, any non-excludable rights).

"Fun bot", "Discord All In One Bot", and related branding are used to identify the Service and remain with the Operator.

# 16. Changes to these terms

The Operator may update these terms from time to time. The "Last updated" date at the top of this page will change when that happens. Continued use of the Service after the updated terms are posted on this website is treated as acceptance, except where the law requires a different process. If you do not agree to the updated terms, stop using the Service and cancel any subscription.

# 17. Governing law

These terms are governed by the laws of Victoria, Australia. The courts of Victoria, Australia, have jurisdiction, subject to any rights you have as a consumer to bring a claim in another forum that the law allows.

# 18. Severability

If a court finds any part of these terms unenforceable, the rest continues in effect. The unenforceable part will be interpreted, as far as possible, to match the intended meaning.

# 19. Contact

If you have questions about these terms, use the Contact Us page on this website. Do not rely on any other address unless it is published there by the Operator.
"""

DEFAULT_PRIVACY = """# Privacy Policy

Last updated: 26 November 2026

This Privacy Policy explains how the Operator (an individual sole operator in Victoria, Australia, known as Whiskey/WarRaven) handles information when you use Discord All In One Bot / Fun bot and the dashboard at discordallinonebot.online. It should be read together with the Terms & Conditions. It has not been reviewed by a lawyer. It is not legal advice.

# What we collect and store

Depending on the features a server uses, the Service may store:

- Discord server IDs and user IDs
- Usernames or display names when they appear in logs or dashboards
- XP, levels, and voice-time totals
- Moderation logs, warnings, and related reasons
- Alt-detection signals, scores, settings, and related log entries
- Server configuration such as channel assignments, level roles, and welcome, leave and ban message text
- Dashboard login session data after you sign in with Discord
- Premium and billing records, including Stripe customer or subscription identifiers

Card numbers and other full payment details are handled by Stripe, not stored in full by the Operator. The bot does not ask you to create a separate password on this website. Sign-in uses Discord OAuth.

# Why we use this information

We use this information to operate the bot and dashboard, to apply server settings, to provide and manage Premium, to help prevent abuse, and to comply with the law.

# Retention and deletion

Information is kept for as long as a server uses the Service and for a reasonable period afterwards, or for as long as needed for billing, security, or legal reasons. You (or a server admin, for that server's data) may request deletion through the Contact Us page. The Operator will take reasonable steps to delete or de-identify stored data, except where it must or reasonably should be kept.

# Third parties

Discord provides the platform the bot runs on. Stripe processes payments. Railway hosts the Service. Each of those providers may process data under their own policies. The Operator does not sell your personal information.

# Access, correction and contact

To ask what is stored, to request correction or deletion, or to raise a privacy concern, use the Contact Us page. If you are in Australia, you may also have rights under the Privacy Act 1988 (Cth) and, where they apply, the Australian Privacy Principles. The Operator is an individual without an ABN; this policy still describes how the Service handles information.

# Changes

This policy may be updated from time to time. The "Last updated" date will change when that happens. The current version will be published on this page.
"""

DEFAULTS = {
    CONTACT_KEY: DEFAULT_CONTACT,
    TERMS_KEY: DEFAULT_TERMS,
    PRIVACY_KEY: DEFAULT_PRIVACY,
}

HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def render_page_body(text: str) -> str:
    """Escape text and turn markdown-like headings and paragraphs into simple HTML."""
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return ""
    blocks = re.split(r"\n{2,}", text)
    out: list[str] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.split("\n")]
        while lines and lines[-1] == "":
            lines.pop()
        while lines and lines[0] == "":
            lines.pop(0)
        if not lines:
            continue
        if len(lines) == 1:
            heading = HEADING_RE.match(lines[0])
            if heading:
                level = min(len(heading.group(1)), 3)  # # -> h1
                tag = f"h{level}"
                out.append(f"<{tag}>{html.escape(heading.group(2).strip())}</{tag}>")
                continue
        escaped = "<br>\n".join(html.escape(line) for line in lines)
        escaped = BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
        out.append(f"<p>{escaped}</p>")
    return "\n".join(out)


CONTACT_PLACEHOLDERS = (
    "[Add your contact email here]",
    "[Add any other contact instructions here, such as a Discord server or a form you prefer]",
)


def strip_contact_placeholders(text: str) -> str:
    """Remove exactly the two placeholder lines (and the blank line after each); nothing else."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i].strip() in CONTACT_PLACEHOLDERS:
            i += 1
            if i < len(lines) and lines[i].strip() == "" and out and out[-1].strip() == "":
                i += 1  # avoid leaving a double blank gap
            elif i < len(lines) and lines[i].strip() == "" and not out:
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


async def load_site_page(db, key: str) -> str:
    default = DEFAULTS[key]
    if db is None:
        return default
    stored = await db.get_site_page(key)
    if stored is None or not str(stored).strip():
        return default
    stored = str(stored)
    if key == CONTACT_KEY:
        cleaned = strip_contact_placeholders(stored)
        if cleaned != stored:
            # One-off clean-up of saved Contact text: only the two placeholder lines are removed.
            await db.set_site_page(key, cleaned)
            stored = cleaned
    return stored


async def save_site_page(db, key: str, body: str) -> None:
    if key not in DEFAULTS:
        raise ValueError("Unknown page")
    await db.set_site_page(key, body.strip())
