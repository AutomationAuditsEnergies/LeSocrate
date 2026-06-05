import React from 'react';
import { DeckQuote } from './DeckTemplates';

export default function QuotableTemplate({ quote, title, ...props }) {
  return <DeckQuote quote={quote} title={title} {...props} />;
}
