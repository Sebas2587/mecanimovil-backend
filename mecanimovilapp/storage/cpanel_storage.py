"""
Storage backend personalizado para subir archivos a cPanel vía FTP.

Este backend permite que Django suba archivos directamente a un servidor cPanel
usando FTP, evitando el problema del sistema de archivos efímero en Render.

Uso:
    En settings.py (o variables de entorno en Render):
    DEFAULT_FILE_STORAGE = 'mecanimovilapp.storage.cpanel_storage.CPanelStorage'
    
    Variables de entorno (NUNCA hardcodear credenciales en el código):
    CPANEL_FTP_HOST=ftp.mecanimovil.cl
    CPANEL_FTP_USER=mecanimovil-media@mecanimovil.cl
    CPANEL_FTP_PASSWORD=tu_contraseña_segura
    CPANEL_FTP_ROOT=/public_html/images/mecanimovil-app-media  # Ruta absoluta en el servidor
    CPANEL_MEDIA_URL=https://mecanimovil.cl/images/mecanimovil-app-media/  # URL pública
"""

import ftplib
import os
import tempfile
from django.core.files.storage import Storage
from django.core.files.base import File
from django.conf import settings
from django.utils.deconstruct import deconstructible
import logging

logger = logging.getLogger(__name__)


@deconstructible
class CPanelStorage(Storage):
    """
    Storage backend que sube archivos a cPanel usando FTP.
    
    Los archivos se suben temporalmente a disco local, luego se transfieren
    vía FTP al servidor cPanel, y finalmente se eliminan del disco local.
    """
    
    def __init__(self, location=None, base_url=None):
        # Normalizar la ruta: si no empieza con /, se asume que es relativa al directorio de la cuenta FTP
        # El valor por defecto debe venir de las variables de entorno, no hardcodeado
        raw_location = location or getattr(settings, 'CPANEL_FTP_ROOT', None)
        if not raw_location:
            raise ValueError(
                "CPANEL_FTP_ROOT no está configurado. "
                "Configura la variable de entorno CPANEL_FTP_ROOT con la ruta en el servidor cPanel. "
                "Ejemplo: 'public_html/images/mecanimovil-app-media' o '/public_html/images/mecanimovil-app-media'"
            )
        # Si la ruta no empieza con /, mantenerla relativa (para cuentas FTP restringidas)
        # Si empieza con /, usar como ruta absoluta
        self.location = raw_location
        self.base_url = base_url or getattr(settings, 'CPANEL_MEDIA_URL', '')
        self.ftp_host = getattr(settings, 'CPANEL_FTP_HOST', None)
        self.ftp_user = getattr(settings, 'CPANEL_FTP_USER', None)
        self.ftp_password = getattr(settings, 'CPANEL_FTP_PASSWORD', None)
        
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            logger.warning("⚠️ [CPanelStorage] Configuración FTP incompleta. Verifica CPANEL_FTP_* en settings.")
    
    def _connect_ftp(self):
        """Establece conexión FTP con el servidor cPanel."""
        try:
            ftp = ftplib.FTP(self.ftp_host)
            ftp.login(self.ftp_user, self.ftp_password)
            ftp.set_pasv(True)  # Modo pasivo (recomendado para la mayoría de servidores)
            return ftp
        except Exception as e:
            logger.error(f"❌ [CPanelStorage] Error conectando a FTP: {e}")
            raise
    
    def _ensure_directory_exists(self, ftp, remote_path):
        """
        Asegura que el directorio remoto existe, creándolo si es necesario.
        
        Args:
            ftp: Conexión FTP activa
            remote_path: Ruta del archivo remoto (puede ser absoluta o relativa)
        """
        # Obtener el directorio del archivo
        directory = os.path.dirname(remote_path)
        
        # Si el directorio está vacío o es solo el nombre del archivo, no hacer nada
        if not directory or directory == '.' or directory == '/':
            return
        
        # Determinar si es ruta absoluta o relativa
        is_absolute = directory.startswith('/')
        
        # Dividir la ruta en partes
        if is_absolute:
            parts = directory.strip('/').split('/')
            current_path = ''
        else:
            parts = directory.split('/')
            current_path = ''
        
        # Crear cada directorio en la ruta si no existe
        for part in parts:
            if not part:  # Saltar partes vacías
                continue
                
            if is_absolute:
                current_path = current_path + '/' + part if current_path else '/' + part
            else:
                current_path = current_path + '/' + part if current_path else part
            
            try:
                # Intentar cambiar al directorio
                ftp.cwd(current_path)
            except ftplib.error_perm:
                # Si no existe, crearlo
                try:
                    ftp.mkd(current_path)
                    logger.info(f"📁 [CPanelStorage] Directorio creado: {current_path}")
                    # Intentar cambiar al directorio recién creado
                    ftp.cwd(current_path)
                except ftplib.error_perm as e:
                    # Puede que ya exista o haya un problema de permisos
                    logger.warning(f"⚠️ [CPanelStorage] No se pudo crear directorio {current_path}: {e}")
                    # Intentar cambiar de nuevo por si acaso
                    try:
                        ftp.cwd(current_path)
                    except:
                        pass
    
    def _save(self, name, content):
        """
        Guarda un archivo en el servidor cPanel vía FTP.
        
        Args:
            name: Nombre del archivo (ej: 'vehiculos/vehicle_123.jpg')
            content: Objeto File de Django con el contenido
            
        Returns:
            str: Nombre del archivo guardado
        """
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            logger.error("❌ [CPanelStorage] Configuración FTP incompleta. No se puede guardar archivo.")
            raise ValueError("Configuración FTP incompleta. Verifica CPANEL_FTP_* en settings.")
        
        # Construir la ruta completa en el servidor
        # Si location es absoluta (empieza con /), usar join normal
        # Si location es relativa, también usar join normal (funciona para ambos casos)
        remote_path = os.path.join(self.location, name).replace('\\', '/')
        # Normalizar: eliminar dobles slashes pero mantener el / inicial si existe
        if remote_path.startswith('//'):
            remote_path = '/' + remote_path.lstrip('/')
        
        # Guardar temporalmente en disco local
        temp_file = None
        try:
            # Crear archivo temporal
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            
            # Escribir contenido al archivo temporal
            for chunk in content.chunks():
                temp_file.write(chunk)
            temp_file.close()
            
            # Subir vía FTP
            ftp = None
            try:
                ftp = self._connect_ftp()
                
                # Asegurar que el directorio existe
                self._ensure_directory_exists(ftp, remote_path)
                
                # Cambiar al directorio del archivo
                remote_dir = os.path.dirname(remote_path)
                if remote_dir:
                    try:
                        ftp.cwd(remote_dir)
                    except:
                        pass
                
                # Subir el archivo
                filename = os.path.basename(remote_path)
                with open(temp_file.name, 'rb') as f:
                    ftp.storbinary(f'STOR {filename}', f)
                
                logger.info(f"✅ [CPanelStorage] Archivo subido: {remote_path}")
                
            finally:
                if ftp:
                    try:
                        ftp.quit()
                    except:
                        ftp.close()
            
            return name
            
        finally:
            # Eliminar archivo temporal
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
    
    def _open(self, name, mode='rb'):
        """
        Abre un archivo desde el servidor cPanel.
        
        Nota: Este método descarga el archivo temporalmente para leerlo.
        En producción, los archivos se sirven directamente desde cPanel vía HTTP.
        """
        # En producción, los archivos se sirven directamente desde cPanel
        # Este método solo se usa en casos especiales
        raise NotImplementedError("Los archivos se sirven directamente desde cPanel vía HTTP")
    
    def exists(self, name):
        """
        Verifica si un archivo existe en el servidor cPanel.
        
        Args:
            name: Nombre del archivo
            
        Returns:
            bool: True si existe, False si no
        """
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            return False
        
        remote_path = os.path.join(self.location, name).replace('\\', '/')
        remote_dir = os.path.dirname(remote_path)
        filename = os.path.basename(remote_path)
        
        ftp = None
        try:
            ftp = self._connect_ftp()
            
            if remote_dir:
                try:
                    ftp.cwd(remote_dir)
                except:
                    return False
            
            # Listar archivos en el directorio
            files = ftp.nlst()
            return filename in files
            
        except Exception as e:
            logger.warning(f"⚠️ [CPanelStorage] Error verificando existencia de {name}: {e}")
            return False
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
    
    def url(self, name):
        """
        Retorna la URL pública del archivo en cPanel.
        
        Args:
            name: Nombre del archivo
            
        Returns:
            str: URL completa del archivo
        """
        if not self.base_url:
            return None
        
        # Asegurar que base_url termina con /
        base = self.base_url.rstrip('/') + '/'
        
        # Construir URL completa
        url = base + name.lstrip('/')
        return url
    
    def delete(self, name):
        """
        Elimina un archivo del servidor cPanel.
        
        Args:
            name: Nombre del archivo a eliminar
        """
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            logger.error("❌ [CPanelStorage] Configuración FTP incompleta. No se puede eliminar archivo.")
            return
        
        remote_path = os.path.join(self.location, name).replace('\\', '/')
        remote_dir = os.path.dirname(remote_path)
        filename = os.path.basename(remote_path)
        
        ftp = None
        try:
            ftp = self._connect_ftp()
            
            if remote_dir:
                try:
                    ftp.cwd(remote_dir)
                except:
                    logger.warning(f"⚠️ [CPanelStorage] No se pudo cambiar al directorio: {remote_dir}")
                    return
            
            # Eliminar archivo
            ftp.delete(filename)
            logger.info(f"🗑️ [CPanelStorage] Archivo eliminado: {remote_path}")
            
        except Exception as e:
            logger.error(f"❌ [CPanelStorage] Error eliminando archivo {name}: {e}")
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
    
    def size(self, name):
        """
        Obtiene el tamaño de un archivo en el servidor cPanel.
        
        Args:
            name: Nombre del archivo
            
        Returns:
            int: Tamaño en bytes, o None si no se puede obtener
        """
        if not all([self.ftp_host, self.ftp_user, self.ftp_password]):
            return None
        
        remote_path = os.path.join(self.location, name).replace('\\', '/')
        remote_dir = os.path.dirname(remote_path)
        filename = os.path.basename(remote_path)
        
        ftp = None
        try:
            ftp = self._connect_ftp()
            
            if remote_dir:
                try:
                    ftp.cwd(remote_dir)
                except:
                    return None
            
            # Obtener tamaño del archivo
            size = ftp.size(filename)
            return size
            
        except Exception as e:
            logger.warning(f"⚠️ [CPanelStorage] Error obteniendo tamaño de {name}: {e}")
            return None
        finally:
            if ftp:
                try:
                    ftp.quit()
                except:
                    ftp.close()
