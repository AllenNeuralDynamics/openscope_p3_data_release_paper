#set document(title: "[-doc.title-]")
#set page(
  paper: "a4",
  margin: (x: 20mm, top: 20mm, bottom: 18mm),
  header: text(size: 8pt, fill: rgb("555555"))[
    OpenScope Predictive Processing Community Project #h(1fr) Preprint draft
  ],
  footer: context align(right, text(size: 9pt, counter(page).display("1"))),
)
#set text(font: "Libertinus Serif", size: 10pt, lang: "en")
#set par(justify: true, leading: 0.6em)
#set heading(numbering: none)
#set figure(gap: 6pt)
#show heading.where(level: 1): set text(size: 14pt, weight: "bold")
#show heading.where(level: 2): set text(size: 11pt, weight: "bold")
#show heading.where(level: 3): set text(size: 10pt, weight: "bold")
#show figure.caption: set text(size: 8.5pt)
#show raw: set text(size: 8pt)
#show raw.where(block: false): code => text(
  font: "DejaVu Sans Mono", size: 7.5pt,
  code.text.clusters().join("\u{200b}"),
)
#show link: set text(fill: black)

[-IMPORTS-]
#import "print.typ": fitPrintImage, printAuthors, printStudy, printNote
#show image.where(height: auto): fitPrintImage
#show figure: set block(breakable: true)
#let warningBlock(body, heading: none) = printNote(body, heading: heading)
#let noteBlock(body, heading: none) = printNote(body, heading: heading)

#block[
  #set par(justify: false)
  #text(size: 21pt, weight: "bold", hyphenate: false)[[-doc.title-]]
]
#v(12pt)

[-CONTENT-]

[# if doc.bibtex #]
#bibliography("[-doc.bibtex-]", title: [References], style: "nature")
[# endif #]