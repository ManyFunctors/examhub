# Colour and language

One colour per meaning. No borrowing. Urgency and certainty use non-colour channels.

## Colours

| Token | Colour | Means | Used for |
|---|---|---|---|
| `--exam` | green | the exam itself | exam date only |
| `--window` | amber | application window + its deadline | registration open/closes |
| `--admit` | blue | admit-card lifecycle | admit card only |
| `--result` | violet | a published result | result only |
| `--done` | grey | finished, nothing published | completed, dates TBA |

## Channels

| Channel | Means |
|---|---|
| solid | can act now |
| hollow | cannot act now |
| dashed | not settled — provisional date, delayed/withdrawn admit card |
| dotted | does not exist yet — not-announced admit card |
| hatched | unused, reserved |

## Admit card

| State | Treatment |
|---|---|
| Released | solid, solid border |
| Announced | hollow, solid border |
| Delayed | solid, dashed |
| Withdrawn | hollow, dashed, heavier |
| Not announced | hollow, dotted |

## Status labels

| Condition | Label |
|---|---|
| open, closes today | `Registration Closes Today` |
| open, ≤7 days | `Registration Closes in 07 Days.` (zero-padded) |
| open, >7 days | `Registration Closes on 2026, December 04` |
| exam next | `Exam on 2026, November 21` |
| result next | `Result Awaited` |
| not open yet | `Registration Opens 2027, January 15` |
| no date published | `Dates to be announced` |
| all past | `Completed` |

Dates always use the site format `2026, October 09`.

## Calendar events

| Kind | Treatment |
|---|---|
| exam | green, solid |
| window | amber, solid |
| deadline | amber, hollow |
| admit card | blue, solid, dashed if provisional |
| result | violet, solid |
| past | same hue, hollow |

## Contrast floors

fill vs `--base` ≥ 1.15:1. text on fill ≥ 5.4:1. Measured in both modes, not eyeballed.
Each token must exist in all three theme blocks in tokens.css.

## Case

Title Case: section headings and link sub-labels. Sentence case: `.detail__label`
row names (Eligibility, Mode, Duration, Negative marking, Venue / centres).

## Rules

- A token is never reused for a second meaning.
- Provisional keeps its kind's colour and gains the dashed treatment.
- Word labels always present; colour is the redundant channel, never the only one.
