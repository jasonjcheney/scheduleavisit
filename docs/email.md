# Sending email (plain language)

ScheduleAVisit can email three kinds of notes. Each one is only about scheduling: a first name, a time, the clinic address, and a link. There are no clinical notes in these emails.

Until the two settings below are saved on Render, nothing is emailed. Booking, saving, and invites still work. The invite form keeps a **Copy link** button either way. The page says “We emailed them” only after the email actually goes out.

## What gets emailed

- A colleague invite, when you use **Referral network** on the dashboard.
- The client, when they book: a confirmation with a link to view or change the visit.
- You, when someone books: a short note with a link to your schedule.
- The day-before and morning-of reminders, for clients always, and for you only if you checked **Email me the day before and the morning of**.

If the email service is down, the visit or invite is still saved. The app writes a short reason in the logs (never the secret key).

## What to add on Render

Open the Render dashboard, click the **scheduleavisit** web service, then **Environment**. Add these two. Do not put them in the git repo.

| Name | Value |
|---|---|
| `RESEND_API_KEY` | the secret key from Resend (it starts with `re_`) |
| `EMAIL_FROM` | `ScheduleAVisit <hello@scheduleavisit.com>` |

Use an address on a domain Resend has verified. `hello@` can be any name you like on that domain. Save. Render will deploy again. You do not need to change code.

`PUBLIC_BASE_URL` is optional. Leave it unset and links in emails use `https://scheduleavisit.com`.

## Sign up and verify the domain

1. Go to [resend.com](https://resend.com) and create an account.
2. In Resend, add the domain **scheduleavisit.com**.
3. Resend shows a few DNS records (usually a TXT record and some CNAME records). Add those wherever scheduleavisit.com’s DNS is managed. This is the same place the website’s domain records already live.
4. Wait until Resend says the domain is **verified**. This can take a few minutes, sometimes longer.
5. In Resend, create an **API key**. Copy it once. That value is `RESEND_API_KEY`.
6. Add `RESEND_API_KEY` and `EMAIL_FROM` on Render, as in the table above.

Resend’s own test domain (`resend.dev`) only delivers to the email on the Resend account. To reach clients and colleagues, verify **scheduleavisit.com** and send from an address on that domain.

The app talks to Resend over HTTPS. No mail server password is required.
