import React from 'react';
import { DeckRecap } from './DeckTemplates';

export default function ChecklistTemplate({ items, checklist, points, ...props }) {
  return <DeckRecap points={points || items || checklist} {...props} />;
}
