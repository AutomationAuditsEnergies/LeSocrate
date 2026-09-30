const CLASS_ACCESS_FAILURES = {
  notFound: {
    kind: 'not-found',
    title: 'Votre classe est introuvable',
    message: 'Vérifiez le lien transmis par votre centre de formation.',
    action: 'home',
  },
  unpublished: {
    kind: 'unpublished',
    title: 'Votre classe n’est pas encore accessible',
    message: 'Elle n’a pas encore été publiée. Contactez votre centre de formation.',
    action: 'home',
  },
  unavailable: {
    kind: 'unavailable',
    title: 'Votre classe est momentanément inaccessible',
    message: 'Nous ne parvenons pas à joindre le service. Réessayez dans quelques instants.',
    action: 'retry',
  },
}

export function getClassAccessFailure(status) {
  if (status === 404) return CLASS_ACCESS_FAILURES.notFound
  if (status === 403) return CLASS_ACCESS_FAILURES.unpublished
  return CLASS_ACCESS_FAILURES.unavailable
}
