import React, { useState } from 'react';
import PlayfulTemplate from '../components/slides/templates/PlayfulTemplate';
import ReflectionTemplate from '../components/slides/templates/ReflectionTemplate';
import CaseStudyTemplate from '../components/slides/templates/CaseStudyTemplate';
import FacilitatorTemplate from '../components/slides/templates/FacilitatorTemplate';
import ChartTemplate from '../components/slides/templates/ChartTemplate';
import StatsTemplate from '../components/slides/templates/StatsTemplate';

export default function TestSlides() {
  const [currentSlide, setCurrentSlide] = useState(0);

  const slides = [
    {
      type: 'playful',
      data: {
        title: "Pourquoi l'automatisation est vitale ?",
        cards: [
          {
            title: "Gain de Temps",
            desc: "Libérer les équipes des tâches répétitives pour se concentrer sur la stratégie.",
            img: "https://images.unsplash.com/photo-1506784983877-45594efa4cbe?q=80&w=2068&auto=format&fit=crop"
          },
          {
            title: "Scalabilité",
            desc: "Permet de traiter 10x plus de leads sans augmenter les effectifs proportionnellement.",
            img: "https://images.unsplash.com/photo-1558494949-ef526b0042a0?q=80&w=2000&auto=format&fit=crop"
          },
          {
            title: "Fiabilité Data",
            desc: "Élimine les erreurs humaines dans la saisie et le transfert des données CRM.",
            img: "https://images.unsplash.com/photo-1555066931-4365d14bab8c?q=80&w=2070&auto=format&fit=crop"
          }
        ]
      }
    },
    {
      type: 'reflection',
      data: {
        title: "Improving Quality through Reflection",
        text: "Reflection is an important step in improving the quality of learning. By evaluating students' learning outcomes regularly, teachers can understand their strengths and areas for improvement. Providing specific and constructive feedback helps students recognize their progress while also improving weaknesses. In addition, involving students in the self-evaluation process encourages them to take more responsibility for their learning."
      }
    },
    {
      type: 'casestudy',
      data: {
        title: "Case Study",
        cases: [
          {
            title: "Example 1",
            desc: "Using an online quiz app to increase engagement regarding technical topics."
          },
          {
            title: "Example 2",
            desc: "Project groups to solve a local environmental problem using data analysis."
          },
          {
            title: "Example 3",
            desc: "Interactive discussion using a digital whiteboard to map ideas collectively."
          }
        ]
      }
    },
    {
      type: 'facilitator',
      data: {
        title: "Teacher as Facilitator\nand Motivator",
        steps: [
          {
            title: "Identify Goals",
            desc: "Define clear objectives for the learning session.",
            icon: "target",
            color: "orange"
          },
          {
            title: "Set Mechanics",
            desc: "Establish the rules and tools needed.",
            icon: "gear",
            color: "purple"
          },
          {
            title: "Spark Action",
            desc: "Launch the activity and energize the group.",
            icon: "flash",
            color: "lime"
          },
          {
            title: "Review Outcomes",
            desc: "Discuss results and validate learning.",
            icon: "flag",
            color: "blue"
          }
        ]
      }
    },
    {
      type: 'chart',
      data: {
        title: "Details 2",
        description: "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n\nUt enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat."
      }
    },
    {
      type: 'stats',
      data: {
        eyebrow: "We Provide To",
        title: "Marketplace",
        description: "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore.",
        stats: [
          { number: "2M" },
          { number: "100K" },
          { number: "82%" }
        ],
        columns: [
          "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore.",
          "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore.",
          "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore."
        ]
      }
    }
  ];

  const renderSlide = () => {
    const slide = slides[currentSlide];
    switch (slide.type) {
      case 'playful':
        return <PlayfulTemplate {...slide.data} badge="TP-CRCD" brandName="Sales Hacking" />;
      case 'reflection':
        return <ReflectionTemplate {...slide.data} badge="TP-CRCD" brandName="SALES HACKING" />;
      case 'casestudy':
        return <CaseStudyTemplate {...slide.data} badge="TP-CRCD" brandName="SALES HACKING" />;
      case 'facilitator':
        return <FacilitatorTemplate {...slide.data} badge="TP-CRCD" brandName="SALES HACKING" />;
      case 'chart':
        return <ChartTemplate {...slide.data} badge="TP-CRCD" brandName="SALES HACKING" />;
      case 'stats':
        return <StatsTemplate {...slide.data} badge="TP-CRCD" brandName="SALES HACKING" />;
      default:
        return null;
    }
  };

  return (
    <div style={{
      margin: 0,
      padding: 0,
      backgroundColor: '#e5e7eb',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: '100vh',
      gap: '2rem'
    }}>
      {renderSlide()}

      {/* Navigation entre les slides */}
      <div style={{
        display: 'flex',
        gap: '1rem',
        alignItems: 'center',
        marginTop: '1rem'
      }}>
        <button
          onClick={() => setCurrentSlide(Math.max(0, currentSlide - 1))}
          disabled={currentSlide === 0}
          style={{
            padding: '0.75rem 1.5rem',
            backgroundColor: currentSlide === 0 ? '#ccc' : '#DC2626',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: currentSlide === 0 ? 'not-allowed' : 'pointer',
            fontFamily: 'Poppins, sans-serif',
            fontWeight: 600
          }}
        >
          ← Précédent
        </button>

        <span style={{
          fontFamily: 'Poppins, sans-serif',
          fontSize: '1rem',
          color: '#333'
        }}>
          Slide {currentSlide + 1} / {slides.length}
        </span>

        <button
          onClick={() => setCurrentSlide(Math.min(slides.length - 1, currentSlide + 1))}
          disabled={currentSlide === slides.length - 1}
          style={{
            padding: '0.75rem 1.5rem',
            backgroundColor: currentSlide === slides.length - 1 ? '#ccc' : '#DC2626',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: currentSlide === slides.length - 1 ? 'not-allowed' : 'pointer',
            fontFamily: 'Poppins, sans-serif',
            fontWeight: 600
          }}
        >
          Suivant →
        </button>
      </div>
    </div>
  );
}
