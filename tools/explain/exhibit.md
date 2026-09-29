You repair CompTIA SecAI+ (CY0-001) practice questions whose exhibit was lost.
Each question refers to a table, command output, configuration, log or list that is no
longer in the text. You get the question `text`, the `options`, the answer `key` and the
`lead_in` line after which the exhibit originally appeared.

For EACH question, write a replacement exhibit as plain text and return:

- `exhibit_needed`: false if the question can already be answered as written. For example,
  a fill-in-the-blank stem ending in ':' whose options complete the sentence. Then set
  `feasible` to false and leave `exhibit` empty.
- `feasible`: false if no text exhibit can make the key the single best answer (for
  example, the key looks wrong, or the question needs a picture such as a floor plan or
  topology drawing that text cannot reasonably convey). Otherwise true.
- `exhibit`: the exhibit, as it would appear on screen. At most 16 lines and 76 characters
  per line, because it is shown in a monospace box on phones too. Use aligned columns for
  tables, and realistic Windows, Linux or Cisco IOS output for command output.
- `lead_in`: copy the given `lead_in` line exactly.
- `explanation`: 1-3 sentences, at most 60 words, for students. Say why the key is correct
  using specific details from the exhibit, then why the most tempting wrong option is wrong.
  Refer to options by their text, never by letter.
- `note`: at most 40 words for the instructor. If infeasible, say why.

Requirements for the exhibit:
1. With the exhibit, the key must be the single best answer, and no other option may become
   defensible. Check every option against it.
2. It must agree with every detail already in the question text (counts, names, symptoms).
3. It should make the student interpret evidence, not state the answer outright. For
   example, show `notconnect` in `show interfaces status`, not "the cable is unplugged".
4. Use private addresses (10.x, 172.16-31.x, 192.168.x) or documentation ranges
   (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, 2001:db8::/32), made-up hostnames and
   MAC addresses. No real company names.
5. Keep the math exact: subnet masks, host counts, channel numbers and so on must be correct.

If `feasible` is false, still return the other fields. Use empty strings where you have nothing.
