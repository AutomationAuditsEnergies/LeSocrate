import React from 'react';
import { DeckCaseStudy } from './DeckTemplates';

export default function PlayfulTemplate({ cards, cases, ...props }) {
  const mappedCases = Array.isArray(cases) && cases.length
    ? cases
    : (Array.isArray(cards) ? cards.map((card, index) => ({
      tag: card.tag || `${String(index + 1).padStart(2, '0')} - Idée`,
      title: card.title,
      desc: card.desc || card.text,
      example: card.example,
    })) : []);

  return <DeckCaseStudy cases={mappedCases} {...props} />;
}
