def enviar_mensagem_whatsapp(destinatario: str, mensagem: str) -> bool:
    """
    Função placeholder para enviar uma mensagem via WhatsApp.

    No futuro, esta função será substituída pela lógica real de integração
    com uma API de WhatsApp (ex: Twilio, Meta API, etc.).

    Por enquanto, ela apenas imprime a mensagem no console para fins de teste.

    Args:
        destinatario: O número de telefone do cliente.
        mensagem: O texto da mensagem a ser enviada.

    Returns:
        True se a mensagem foi "enviada" com sucesso, False caso contrário.
    """
    print("\n" + "="*50)
    print(f"SIMULANDO ENVIO DE WHATSAPP")
    print(f"Para: {destinatario}")
    print(f"Mensagem: \n{mensagem}")
    print("="*50 + "\n")
    
    # Simula que o envio sempre funciona
    return True
