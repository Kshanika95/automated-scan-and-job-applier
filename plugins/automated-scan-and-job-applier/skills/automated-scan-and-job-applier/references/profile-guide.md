# Building the profile, facts, master resume and bullet bank

The profile is the single source of truth. The tailoring and form-answering code can only use what is written
here, so time spent on this step pays off on every application.

## 1. Gather material
Ask for everything: current and past resumes (all versions), cover letters, portfolio or case studies, LinkedIn
text, performance reviews they're happy to share, and an interview history if they have one. Read every file
completely before writing anything. If files mention other people (a friend's resume used as a template), never
take facts from them.

## 2. Draft `profile.md` (use `templates/profile.md` as the outline)
- **Work history:** one canonical title, company, location and date range per role. Past resume versions often
  disagree (e.g. "UX Designer & Researcher" vs "Senior UX Researcher"); list the variants and ask which is
  official. The chosen title goes on every resume; older variants go under "never use".
- **Bullets:** collect the strongest real bullets per role. Keep the specifics (counts, domains, methods).
- **Metrics:** for each number, record exactly what it measures and how it may be phrased ("6,000+ users per
  quarter, never monthly"). Numbers that appear in only one version, or that the person can't confirm, go under
  "retired claims".
- **Education & credentials:** only completed degrees and current certifications. Ask about anything unclear
  (an abandoned degree must never appear).
- **Gaps:** ask how they want gaps described. Only describe real work (e.g. genuine freelance clients).
- **Case studies:** project, role, team, method, scale, outcome. These feed essay answers and cover letters.
- **Search criteria:** roles, adjacent roles, levels, locations, time zone, salary floor, industries,
  employment types. These become `search.json`.
- **Open questions:** list them, ask them, record the answers with the date.

Ask in small batches (3-6 questions at a time), lead with the decisions that change the most, and suggest an
answer when you have a recommendation.

## 3. `facts.json` (form answers)
Copy `templates/facts.json` and fill it with confirmed values only. Keep `null` for anything not given:
required questions that need it go to the person instead of being guessed. Common ones to ask about up
front, because forms often require them: middle name (or "none"), street address and ZIP, pronouns (or "decline"),
a portfolio PDF if they apply to design roles, work authorization and sponsorship (now and future), EEO choices
("decline" is always valid), start date or notice period, previous employers.

## 4. `resume/master.json` and `resume/bank.json`
- `master.json` is the approved resume: name, title, contact list (`"text|url"` for links), headline, summary,
  experience (each with an `id`), skills rows, education, certifications.
- `bank.json` maps each job `id` to its bullets: `min`/`max` bullet counts, every approved bullet with an `id`,
  `master: true` on the default set, and `group` on bullets that reuse the same metric (at most one per resume).
  Add `titles` (header titles the tailor may choose from), `skill_categories`, `skills_vocab` (every skill
  the person truly has; the tailor can only use these exact strings) and `forbidden_phrases` (regexes for
  rejected claims, e.g. a degree they didn't finish).
- Bold the key phrase of each bullet with `**...**`. Avoid special characters like → and ✓, which some
  applicant tracking systems garble.

## 5. Build and approve the master PDF
```bash
python3 -I ~/job-applier/resume/build_resume.py ~/job-applier/resume/master.json "~/job-applier/resume/out/<Full Name> Resume.pdf"
```
The builder tries font sizes and spacing until the PDF is exactly `resume_pages` pages with the last page
filled to the bottom, no orphan one-word lines, and a clean text layer. If it can't, it says whether the
content is too long ("overflow") or too short ("underfill"): add or remove bullets, or switch `resume_pages`.
Show the person both pages, and don't move on until they approve.
