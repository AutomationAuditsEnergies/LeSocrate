import { FooterBrand } from "@/sections/Footer/components/FooterBrand";
import { FooterContact } from "@/sections/Footer/components/FooterContact";
import { FooterLinks } from "@/sections/Footer/components/FooterLinks";
import { FooterBottom } from "@/sections/Footer/components/FooterBottom";

export const Footer = () => {
  return (
    <footer className="box-border caret-transparent text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] outline-[3px] relative no-underline w-full pt-[46.1538px] pb-[38.4615px] px-[19.2308px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:pt-[42.6667px] md:pb-[35.5556px] md:px-[35.5556px]">
      <div className="box-border caret-transparent gap-x-[23.0769px] flex flex-col text-[15.3846px] tracking-[-0.107692px] leading-[21.5385px] max-w-[1153.85px] outline-[3px] gap-y-[23.0769px] no-underline w-full mx-auto md:gap-x-[35.5556px] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:max-w-[1066.67px] md:gap-y-[35.5556px]">
        <FooterBrand />
        <div className="box-border caret-transparent gap-x-[19.2308px] flex flex-col text-[15.3846px] justify-between tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] gap-y-[19.2308px] no-underline md:gap-x-[17.7778px] md:flex-row md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px] md:gap-y-[17.7778px]">
          <FooterContact />
          <FooterLinks />
        </div>
        <div className="items-center box-border caret-transparent flex text-[15.3846px] h-px justify-center tracking-[-0.107692px] leading-[21.5385px] min-h-[auto] min-w-[auto] outline-[3px] relative no-underline w-full md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]">
          <div className="bg-white/10 box-border caret-transparent text-[15.3846px] h-full tracking-[-0.107692px] leading-[21.5385px] outline-[3px] absolute no-underline w-screen top-[0%] md:text-[14.2222px] md:tracking-[-0.0995556px] md:leading-[19.9111px]"></div>
        </div>
        <FooterBottom />
      </div>
    </footer>
  );
};
