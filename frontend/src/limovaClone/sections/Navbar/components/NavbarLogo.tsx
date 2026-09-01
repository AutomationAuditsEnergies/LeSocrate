export const NavbarLogo = () => {
  return (
    <a
      href="/"
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-violet-400 focus-visible:ring-offset-2 focus-visible:ring-offset-black md:h-9 md:w-9"
      aria-label="Cadrenza, retour à l’accueil"
    >
      <img src="/socrate-mark.svg" alt="" className="h-full w-full object-contain" />
    </a>
  );
};
