You audit CompTIA SecAI+ (CY0-001) practice questions that include an exhibit
(a table, command output, configuration or log shown between [EXHIBIT] and [END EXHIBIT]).
You do NOT get the answer key. `select` says how many options are correct.

Some questions come with exhibit images, sent after the JSON as "Exhibit image N for question
<id>". They are part of that question (the table, screenshot or output its text refers to):
treat them as present and read them carefully.

For EACH question:
1. Solve it yourself from the question text, the exhibit and standard SecAI+ knowledge.
   Put your answer letters in `answer`.
2. Judge every option against the exhibit and the text. In `options`, give each letter a
   verdict: "correct", "incorrect" or "also_defensible" (a reasonable expert could argue
   for it from the given data). Add a short `reason` that cites the exhibit data.
3. `sufficient`: true if the text and exhibit contain all the data needed to reach the
   answer (general SecAI+ knowledge is expected; missing situational data is not).
4. `unique`: true if exactly the required number of options holds up and no other option
   is also defensible.
5. `issues`: an empty string, or a precise description of any problem, such as arithmetic
   errors (subnet sizes, host counts, totals), values that contradict the question text,
   unrealistic output, an exhibit that states the answer outright, or data that points to
   a different answer. At most 60 words.
6. `fix`: an empty string, or the smallest change to the exhibit that would make exactly
   one answer correct. At most 60 words.

Be rigorous and skeptical. Recompute every number. Do not assume the exhibit is correct.
