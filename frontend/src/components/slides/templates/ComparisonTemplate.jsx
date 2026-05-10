import React from 'react';
import styles from './ComparisonTemplate.module.css';

// cols: [{ label, color, icon, bg, items: [string] }]
const ComparisonTemplate = ({
  title = 'Deux façons de conclure un appel',
  cols = [
    {
      label: 'À éviter',
      color: '#E07A6F',
      icon: '✗',
      bg: '#FDF4F3',
      items: [
        '"OK ben je vous envoie une brochure."',
        'Pas de date de rappel fixée.',
        'Le client ne sait pas quoi faire ensuite.',
        'Vous raccrochez sans engagement mutuel.',
      ],
    },
    {
      label: 'Bonne pratique',
      color: '#A7B85A',
      icon: '✓',
      bg: '#F4F7E6',
      items: [
        '"Je suis disponible jeudi 14h30 ou vendredi 10h — lequel vous convient ?"',
        'Créneau précis proposé immédiatement.',
        'Le client sait exactement ce qui suit.',
        'Les deux parties sont engagées sur une date.',
      ],
    },
  ],
  badge = 'TP-CRCD',
  brandName = 'SALES HACKING',
}) => (
  <div className={styles.slide}>
    <div className={styles.header}>
      <div className={styles.badge}>{badge}</div>
      <span className={styles.brandName}>{brandName}</span>
    </div>

    <div className={styles.body}>
      <h1 className={styles.title}>{title}</h1>

      <div className={styles.cols}>
        {cols.map((col, i) => (
          <React.Fragment key={i}>
            <div
              className={styles.col}
              style={{ '--col-color': col.color, '--col-bg': col.bg }}
            >
              <div className={styles.colHeader}>
                <span className={styles.colIcon}>{col.icon}</span>
                <span className={styles.colLabel}>{col.label}</span>
              </div>
              <div className={styles.colBody}>
                {col.items.map((item, j) => (
                  <div key={j} className={styles.item}>
                    <p className={styles.itemText}>{item}</p>
                  </div>
                ))}
              </div>
            </div>

            {i < cols.length - 1 && (
              <div className={styles.separator}>
                <div className={styles.vsBadge}>VS</div>
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
    </div>
  </div>
);

export default ComparisonTemplate;
