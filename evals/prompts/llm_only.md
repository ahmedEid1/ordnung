<!-- version: 2 -->
Today is {{weekday}}, {{today}} — use this as today's date for this letter, even if other context
mentions a different date. The person lives in {{region_name}} ({{region}}), Germany. Use the public
holidays of that Land unless the letter shows that the relevant office sits in another Land.

{{document}}

Return the JSON record for this letter. Compute every due date exactly, applying current German law
as of today (for example the rules on when a posted letter from an authority counts as delivered,
§§ 187, 188 and 193 BGB and their counterparts in tax, administrative and social law, and public
holidays).
