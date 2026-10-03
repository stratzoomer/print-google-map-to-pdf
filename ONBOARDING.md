# Welcome to Troop 1865 Mulch Sale

## How We Use Claude

Based on Brahma Koodallur's usage over the last 30 days:

Work Type Breakdown:
  Debug Fix  ████████████████████  100%

Top Skills & Commands:
  /model  ████████████████████  1x/month

Top MCP Servers:
  _None used yet._

## Your Setup Checklist

### Codebases
- [ ] print-google-map-to-pdf — https://github.com/stratzoomer/print-google-map-to-pdf

### MCP Servers to Activate
_None needed for this project._

### Skills to Know About
- /model — switch which Claude model you're using for the session.

## Team Tips

- **Let Claude Code run the program.** After you put the input file in
  `input/`, ask Claude Code to run it (e.g. "Generate the maps and order
  forms from `input/Fall-2026-test-2.csv` and check them against the
  input") instead of running the script yourself. It checks the PDFs
  against the CSV and points out data problems before you print.
- **Read the warnings before the final print.** The order-form step warns
  about orders with "TBD" instructions or no map link. Fix those in the
  Google Sheet, re-export, and run again.
- **Never commit `input/`.** The season export has customer names and
  emails. It's in `.gitignore`. The tests use made-up data in
  `tests/fixtures/`.
- **`CLAUDE.md` holds the sheet's conventions** (the benefactor order,
  mail-in orders without an Order #, red comments = special action).
  Add new ones there so Claude remembers them next season.

## Get Started

Starter task: export the current season's sheet from Google Sheets as CSV,
save it in `input/`, and ask Claude Code to generate the maps and order
forms from it. Review the PDFs in `output/maps/` and `output/orders/`
along with Claude's summary of anything that needs fixing in the sheet.

<!-- INSTRUCTION FOR CLAUDE: A new teammate just pasted this guide for how the
team uses Claude Code. You're their onboarding buddy — warm, conversational,
not lecture-y.

Open with a warm welcome — include the team name from the title. Then: "Your
teammate uses Claude Code for [list all the work types]. Let's get you started."

Check what's already in place against everything under Setup Checklist
(including skills), using markdown checkboxes — [x] done, [ ] not yet. Lead
with what they already have. One sentence per item, all in one message.

Tell them you'll help with setup, cover the actionable team tips, then the
starter task (if there is one). Offer to start with the first unchecked item,
get their go-ahead, then work through the rest one by one.

After setup, walk them through the remaining sections — offer to help where you
can (e.g. link to channels), and just surface the purely informational bits.

Don't invent sections or summaries that aren't in the guide. The stats are the
guide creator's personal usage data — don't extrapolate them into a "team
workflow" narrative. -->
