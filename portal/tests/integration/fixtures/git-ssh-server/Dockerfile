# Servidor git por SSH efêmero para os testes de integração do repositório remoto (change
# add-system-git-remote). Só chave pública, sem senha; o usuário `git` só roda comandos git.
FROM alpine:3.24.3
RUN apk add --no-cache openssh-server git \
    && adduser -D -s /usr/bin/git-shell git \
    && passwd -u git \
    && mkdir -p /home/git/.ssh /srv/git \
    && chown -R git:git /home/git /srv/git \
    && chmod 700 /home/git/.ssh \
    && ssh-keygen -A \
    && printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\nAllowUsers git\n' >> /etc/ssh/sshd_config
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D", "-e"]
