import { HeroSection } from "@/sections/HeroSection";
import { AgentsSection } from "@/sections/AgentsSection";
import { CharlySection } from "@/sections/CharlySection";
import { TestimonialsSection } from "@/sections/TestimonialsSection";
import { IntegrationsSection } from "@/sections/IntegrationsSection";
import { StepsSection } from "@/sections/StepsSection";
import { FaqSection } from "@/sections/FaqSection";
import { TrustLogosSection } from "@/sections/TrustLogosSection";
import { CtaSection } from "@/sections/CtaSection";
import { Footer } from "@/sections/Footer";

export const MainContent = () => {
  return (
    <main className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] no-underline overflow-clip pt-[46.1538px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:pt-[28.4444px]">
      <HeroSection />
      <AgentsSection />
      <CharlySection />
      <TestimonialsSection />
      <IntegrationsSection />
      <StepsSection />
      <FaqSection />
      <TrustLogosSection />
      <CtaSection />
      <Footer />
    </main>
  );
};
