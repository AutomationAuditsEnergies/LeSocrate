import React from 'react';
import { DeckStatement } from './DeckTemplates';

export default function QuotableTemplate({ quote, title, ...props }) {
  return <DeckStatement title={title || quote} {...props} />;
}
